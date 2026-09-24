// Package llm is the client for the local model server.
//
// The agent generates through Ollama (design §4): one HTTP call per
// generation, never streamed, so a reply is one JSON object rather than a
// sequence of them. Tool schemas arrive in milestone 5 and context deadlines
// in milestone 4; this is the plain request/response floor underneath both.
package llm

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// DefaultBaseURL is where Ollama listens unless told otherwise.
const DefaultBaseURL = "http://localhost:11434"

// Client is a handle on one Ollama server and one model.
type Client struct {
	baseURL string
	model   string
	http    *http.Client
}

// New returns a Client for model on the server at baseURL. A baseURL without
// a scheme gets http:// — OLLAMA_HOST is conventionally written "host:port",
// which is not a URL http.NewRequest will accept.
func New(baseURL, model string) *Client {
	if !strings.Contains(baseURL, "://") {
		baseURL = "http://" + baseURL
	}
	return &Client{
		baseURL: strings.TrimRight(baseURL, "/"),
		model:   model,
		// A blunt ceiling so a wedged server can't hang the agent forever.
		// Milestone 4 replaces it with a per-call context deadline.
		http: &http.Client{Timeout: 5 * time.Minute},
	}
}

// Model reports the model this client generates with.
func (c *Client) Model() string { return c.model }

// GenerateRequest is the part of a generation the caller varies. The model
// name and the stream setting belong to the client, not to the call.
type GenerateRequest struct {
	Prompt string

	// Think turns a thinking model's reasoning pass on or off. It is a
	// pointer because "off" and "unsaid" are different requests: nil leaves
	// the model's own default alone, while Bool(false) actively suppresses
	// the reasoning pass. A plain bool could only express one of them.
	Think *bool

	Options *Options
}

// Options are Ollama's sampling knobs. The pointers are deliberate: 0 is a
// meaningful temperature and a meaningful seed, so those fields cannot use
// omitempty on a plain value without losing the ability to send zero.
type Options struct {
	NumPredict  int      `json:"num_predict,omitempty"`
	Temperature *float64 `json:"temperature,omitempty"`
	Seed        *int     `json:"seed,omitempty"`
}

// generateBody is the wire format of POST /api/generate.
type generateBody struct {
	Model  string `json:"model"`
	Prompt string `json:"prompt"`

	// Stream must be sent even when false. Ollama streams by default, and
	// `json:"stream,omitempty"` would drop the false and hand us a sequence
	// of JSON objects that Decode reads only the first of.
	Stream bool `json:"stream"`

	Think   *bool    `json:"think,omitempty"`
	Options *Options `json:"options,omitempty"`
}

// GenerateResponse is one non-streamed reply from /api/generate.
//
// The duration fields are nanosecond counts on the wire, which is exactly
// what a time.Duration is, so they decode straight into one.
type GenerateResponse struct {
	Model      string    `json:"model"`
	CreatedAt  time.Time `json:"created_at"`
	Response   string    `json:"response"`
	Thinking   string    `json:"thinking"`
	Done       bool      `json:"done"`
	DoneReason string    `json:"done_reason"`

	PromptEvalCount int `json:"prompt_eval_count"`
	EvalCount       int `json:"eval_count"`

	TotalDuration      time.Duration `json:"total_duration"`
	LoadDuration       time.Duration `json:"load_duration"`
	PromptEvalDuration time.Duration `json:"prompt_eval_duration"`
	EvalDuration       time.Duration `json:"eval_duration"`
}

// Truncated reports whether the model stopped because it ran out of token
// budget rather than because it finished. A truncated draft is a broken
// draft: half a table is worse than no table.
func (r GenerateResponse) Truncated() bool { return r.DoneReason == "length" }

// Generate sends one prompt and returns the whole reply.
func (c *Client) Generate(req GenerateRequest) (GenerateResponse, error) {
	body := generateBody{
		Model:   c.model,
		Prompt:  req.Prompt,
		Stream:  false,
		Think:   req.Think,
		Options: req.Options,
	}

	var out GenerateResponse
	if err := c.post("/api/generate", body, &out); err != nil {
		return GenerateResponse{}, err
	}
	return out, nil
}

// Version reports the Ollama server's version, and doubles as a reachability
// check that costs no GPU time.
func (c *Client) Version() (string, error) {
	var out struct {
		Version string `json:"version"`
	}
	if err := c.get("/api/version", &out); err != nil {
		return "", err
	}
	return out.Version, nil
}

func (c *Client) post(path string, in, out any) error {
	payload, err := json.Marshal(in)
	if err != nil {
		return fmt.Errorf("llm: encoding request for %s: %w", path, err)
	}
	req, err := http.NewRequest(http.MethodPost, c.baseURL+path, bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("llm: building request for %s: %w", path, err)
	}
	req.Header.Set("Content-Type", "application/json")
	return c.do(req, out)
}

func (c *Client) get(path string, out any) error {
	req, err := http.NewRequest(http.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return fmt.Errorf("llm: building request for %s: %w", path, err)
	}
	return c.do(req, out)
}

func (c *Client) do(req *http.Request, out any) error {
	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("llm: %s %s: %w", req.Method, req.URL.Path, err)
	}
	// Close every body, including the ones we never read: an unclosed body
	// holds its connection out of the pool until the GC gets to it.
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("llm: %s %s: %s", req.Method, req.URL.Path, serverError(resp))
	}
	if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
		return fmt.Errorf("llm: decoding %s reply: %w", req.URL.Path, err)
	}
	return nil
}

// serverError turns a failed response into something readable. Ollama reports
// most failures as {"error": "..."}, but a mistyped path is answered by the
// HTTP mux in plain text, so the body is only treated as JSON if it parses.
func serverError(resp *http.Response) string {
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4<<10))
	if err != nil || len(bytes.TrimSpace(body)) == 0 {
		return resp.Status
	}

	var wire struct {
		Error string `json:"error"`
	}
	if json.Unmarshal(body, &wire) == nil && wire.Error != "" {
		return fmt.Sprintf("%s: %s", resp.Status, wire.Error)
	}
	return fmt.Sprintf("%s: %s", resp.Status, bytes.TrimSpace(body))
}

// Bool, Float64 and Int return pointers to their argument, for the option
// fields where zero and unset have to stay distinguishable.
func Bool(v bool) *bool          { return &v }
func Float64(v float64) *float64 { return &v }
func Int(v int) *int             { return &v }
