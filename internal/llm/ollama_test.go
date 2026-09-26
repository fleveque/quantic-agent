package llm_test

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/fleveque/quantic-agent/internal/llm"
)

// fixture returns a reply captured from a real Ollama server. Anything under
// testdata/ is invisible to the go tool, so these never reach a build.
func fixture(t *testing.T, name string) []byte {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("testdata", name))
	if err != nil {
		t.Fatalf("reading fixture %s: %v", name, err)
	}
	return b
}

// serveFixture answers every request with one captured reply, and records the
// request body it was sent.
func serveFixture(t *testing.T, name string, got *map[string]any) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got != nil {
			// t.Errorf is safe from the server's goroutine; t.Fatalf is not,
			// because it stops the goroutine it is called from and this one
			// isn't the test's.
			if err := json.NewDecoder(r.Body).Decode(got); err != nil {
				t.Errorf("decoding request body: %v", err)
			}
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write(fixture(t, name))
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestGenerateDecodesReply(t *testing.T) {
	var sent map[string]any
	srv := serveFixture(t, "generate.json", &sent)

	c := llm.New(srv.URL, "quantic-9b:latest")
	resp, err := c.Generate(llm.GenerateRequest{
		Prompt: "Reply with exactly: ok",
		Think:  llm.Bool(false),
	})
	if err != nil {
		t.Fatalf("Generate: %v", err)
	}

	if resp.Response != "ok" {
		t.Errorf("Response = %q, want %q", resp.Response, "ok")
	}
	if resp.DoneReason != "stop" {
		t.Errorf("DoneReason = %q, want %q", resp.DoneReason, "stop")
	}
	if resp.Truncated() {
		t.Error("Truncated() = true, want false")
	}
	if resp.EvalCount != 2 {
		t.Errorf("EvalCount = %d, want 2", resp.EvalCount)
	}
	// 205098000 nanoseconds on the wire is a time.Duration of 205.098ms.
	if want := 205098 * time.Microsecond; resp.EvalDuration != want {
		t.Errorf("EvalDuration = %v, want %v", resp.EvalDuration, want)
	}
	if resp.CreatedAt.IsZero() {
		t.Error("CreatedAt is zero, want the timestamp parsed from RFC 3339")
	}

	if sent["model"] != "quantic-9b:latest" {
		t.Errorf("request model = %v, want quantic-9b:latest", sent["model"])
	}
	if sent["stream"] != false {
		t.Errorf("request stream = %v, want false — Ollama streams unless told not to", sent["stream"])
	}
	if sent["think"] != false {
		t.Errorf("request think = %v, want false", sent["think"])
	}
}

func TestGenerateReportsTruncation(t *testing.T) {
	srv := serveFixture(t, "generate-thinking.json", nil)

	resp, err := llm.New(srv.URL, "quantic-9b:latest").Generate(llm.GenerateRequest{Prompt: "hi"})
	if err != nil {
		t.Fatalf("Generate: %v", err)
	}

	if !resp.Truncated() {
		t.Errorf("Truncated() = false, want true (done_reason %q)", resp.DoneReason)
	}
	// A thinking model spends its budget on the reasoning pass first, so a
	// truncated reply can carry thinking and no answer at all.
	if resp.Response != "" {
		t.Errorf("Response = %q, want it empty", resp.Response)
	}
	if resp.Thinking == "" {
		t.Error("Thinking is empty, want the captured reasoning text")
	}
}

func TestGenerateOmitsUnsetOptions(t *testing.T) {
	var sent map[string]any
	srv := serveFixture(t, "generate.json", &sent)

	_, err := llm.New(srv.URL, "m").Generate(llm.GenerateRequest{Prompt: "hi"})
	if err != nil {
		t.Fatalf("Generate: %v", err)
	}

	if _, ok := sent["think"]; ok {
		t.Errorf("request carries think = %v, want the field absent", sent["think"])
	}
	if _, ok := sent["options"]; ok {
		t.Errorf("request carries options = %v, want the field absent", sent["options"])
	}
}

func TestGenerateSendsZeroValuedOptions(t *testing.T) {
	var sent map[string]any
	srv := serveFixture(t, "generate.json", &sent)

	_, err := llm.New(srv.URL, "m").Generate(llm.GenerateRequest{
		Prompt:  "hi",
		Options: &llm.Options{Temperature: llm.Float64(0), Seed: llm.Int(0)},
	})
	if err != nil {
		t.Fatalf("Generate: %v", err)
	}

	opts, ok := sent["options"].(map[string]any)
	if !ok {
		t.Fatalf("request options = %v, want an object", sent["options"])
	}
	// The point of the pointers: 0 is a real temperature and a real seed.
	if opts["temperature"] != float64(0) {
		t.Errorf("options.temperature = %v, want 0", opts["temperature"])
	}
	if opts["seed"] != float64(0) {
		t.Errorf("options.seed = %v, want 0", opts["seed"])
	}
	if _, ok := opts["num_predict"]; ok {
		t.Errorf("options.num_predict = %v, want it absent when unset", opts["num_predict"])
	}
}

func TestVersion(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/version" {
			t.Errorf("path = %q, want /api/version", r.URL.Path)
		}
		w.Write([]byte(`{"version":"0.30.3"}`))
	}))
	t.Cleanup(srv.Close)

	got, err := llm.New(srv.URL, "m").Version()
	if err != nil {
		t.Fatalf("Version: %v", err)
	}
	if got != "0.30.3" {
		t.Errorf("Version() = %q, want %q", got, "0.30.3")
	}
}

func TestServerErrors(t *testing.T) {
	// Every body here is what a real Ollama 0.34.4 sent for that request.
	tests := []struct {
		name          string
		status        int
		body          string
		wantMessage   string
		wantNotFound  bool
		wantInMessage []string
	}{
		{
			name:         "unknown model",
			status:       http.StatusNotFound,
			body:         string(fixture(t, "generate-model-not-found.json")),
			wantMessage:  "model 'no-such-model:latest' not found",
			wantNotFound: true,
		},
		{
			// A mistyped path never reaches Ollama's handlers, so the body is
			// the router's plain text, and the 404 is not about a model.
			name:        "plain text error body",
			status:      http.StatusNotFound,
			body:        "404 page not found\n",
			wantMessage: "404 page not found",
		},
		{
			name:        "malformed request",
			status:      http.StatusBadRequest,
			body:        `{"error":"invalid character 'n' looking for beginning of object key string"}`,
			wantMessage: "invalid character 'n' looking for beginning of object key string",
		},
		{
			name:        "empty error body",
			status:      http.StatusInternalServerError,
			body:        "",
			wantMessage: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tt.status)
				w.Write([]byte(tt.body))
			}))
			t.Cleanup(srv.Close)

			_, err := llm.New(srv.URL, "m").Generate(llm.GenerateRequest{Prompt: "hi"})
			if err == nil {
				t.Fatal("Generate returned no error, want one")
			}

			var apiErr *llm.APIError
			if !errors.As(err, &apiErr) {
				t.Fatalf("error %q is not an *llm.APIError", err)
			}
			if apiErr.StatusCode != tt.status {
				t.Errorf("StatusCode = %d, want %d", apiErr.StatusCode, tt.status)
			}
			if apiErr.Message != tt.wantMessage {
				t.Errorf("Message = %q, want %q", apiErr.Message, tt.wantMessage)
			}
			if got := errors.Is(err, llm.ErrModelNotFound); got != tt.wantNotFound {
				t.Errorf("errors.Is(err, ErrModelNotFound) = %v, want %v", got, tt.wantNotFound)
			}
			// The server answered, so whatever went wrong, it isn't absent.
			if errors.Is(err, llm.ErrUnavailable) {
				t.Errorf("errors.Is(err, ErrUnavailable) = true for a server that replied")
			}
			// The message still reads as one line with the status in it.
			if want := strconv.Itoa(tt.status); !strings.Contains(err.Error(), want) {
				t.Errorf("error %q, want it to mention %s", err, want)
			}
		})
	}
}

// deadAddr is an address nothing listens on, as with a stopped Ollama. Port 1
// is privileged and outside the range the OS hands out to test servers. The
// port of a closed httptest server is not safe for this: go test runs package
// binaries in parallel, and another one's server can be given that port a
// moment later.
const deadAddr = "http://127.0.0.1:1"

func TestUnavailableWhenNothingListens(t *testing.T) {
	_, err := llm.New(deadAddr, "m").Version()

	if !errors.Is(err, llm.ErrUnavailable) {
		t.Fatalf("errors.Is(err, ErrUnavailable) = false for %q", err)
	}
	// Both %w verbs matter: the network cause is still reachable too.
	if !errors.Is(err, syscall.ECONNREFUSED) {
		t.Errorf("errors.Is(err, ECONNREFUSED) = false for %q", err)
	}
	var apiErr *llm.APIError
	if errors.As(err, &apiErr) {
		t.Errorf("errors.As found an *APIError in %q, but no reply was received", err)
	}
}

func TestUnavailableWhenConnectionDrops(t *testing.T) {
	// The server accepts the connection and closes it without replying, as
	// happens when Ollama restarts in the middle of a request.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, _, err := w.(http.Hijacker).Hijack()
		if err != nil {
			t.Errorf("hijacking the connection: %v", err)
			return
		}
		conn.Close()
	}))
	t.Cleanup(srv.Close)

	_, err := llm.New(srv.URL, "m").Generate(llm.GenerateRequest{Prompt: "hi"})

	if !errors.Is(err, llm.ErrUnavailable) {
		t.Errorf("errors.Is(err, ErrUnavailable) = false for %q", err)
	}
}

func TestUnknownHostIsNotUnavailable(t *testing.T) {
	// .invalid is reserved and never resolves. An unresolvable name is almost
	// always a typo in OLLAMA_HOST, which should fail rather than be waited on.
	_, err := llm.New("http://no-such-host.invalid:11434", "m").Version()

	if err == nil {
		t.Fatal("Version returned no error, want one")
	}
	if errors.Is(err, llm.ErrUnavailable) {
		t.Errorf("errors.Is(err, ErrUnavailable) = true for %q, want an ordinary failure", err)
	}
}

func TestGenerateRejectsUnparseableReply(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("{not json"))
	}))
	t.Cleanup(srv.Close)

	_, err := llm.New(srv.URL, "m").Generate(llm.GenerateRequest{Prompt: "hi"})
	if err == nil {
		t.Fatal("Generate returned no error, want one")
	}
	if !strings.Contains(err.Error(), "decoding") {
		t.Errorf("error %q, want it to mention decoding", err)
	}
	// A reply that arrived but made no sense is neither kind of known failure.
	var apiErr *llm.APIError
	if errors.As(err, &apiErr) || errors.Is(err, llm.ErrUnavailable) {
		t.Errorf("error %q classified as an API or availability error, want neither", err)
	}
}

func TestNewAcceptsHostWithoutScheme(t *testing.T) {
	srv := serveFixture(t, "generate.json", nil)

	// OLLAMA_HOST is conventionally "host:port" with no scheme.
	hostPort := strings.TrimPrefix(srv.URL, "http://")

	if _, err := llm.New(hostPort, "m").Generate(llm.GenerateRequest{Prompt: "hi"}); err != nil {
		t.Fatalf("Generate against %q: %v", hostPort, err)
	}
}

func TestModels(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/tags" {
			t.Errorf("path = %q, want /api/tags", r.URL.Path)
		}
		w.Write(fixture(t, "tags.json"))
	}))
	t.Cleanup(srv.Close)

	models, err := llm.New(srv.URL, "qwen3.5:9b").Models()
	if err != nil {
		t.Fatalf("Models: %v", err)
	}
	if len(models) != 3 {
		t.Fatalf("got %d models, want the 3 in the fixture", len(models))
	}

	got := models[0]
	if got.Name != "qwen3.5:9b" {
		t.Errorf("Name = %q, want qwen3.5:9b", got.Name)
	}
	if got.Details.ParameterSize != "9.7B" {
		t.Errorf("ParameterSize = %q, want 9.7B", got.Details.ParameterSize)
	}
	if got.Details.QuantizationLevel != "Q4_K_M" {
		t.Errorf("QuantizationLevel = %q, want Q4_K_M", got.Details.QuantizationLevel)
	}
	if got.Details.ContextLength != 262144 {
		t.Errorf("ContextLength = %d, want 262144", got.Details.ContextLength)
	}
	if got.Size != 6594474711 {
		t.Errorf("Size = %d, want 6594474711", got.Size)
	}

	// Milestone 5 needs tool-calling, so the capability list is worth
	// reading rather than assuming.
	if !got.Supports("tools") {
		t.Errorf("Supports(tools) = false, want true (capabilities: %v)", got.Capabilities)
	}
	if !got.Supports("thinking") {
		t.Errorf("Supports(thinking) = false, want true (capabilities: %v)", got.Capabilities)
	}
	if got.Supports("telepathy") {
		t.Error("Supports(telepathy) = true, want false")
	}
}

func TestRunning(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/ps" {
			t.Errorf("path = %q, want /api/ps", r.URL.Path)
		}
		w.Write(fixture(t, "ps.json"))
	}))
	t.Cleanup(srv.Close)

	running, err := llm.New(srv.URL, "qwen3.5:9b").Running()
	if err != nil {
		t.Fatalf("Running: %v", err)
	}
	if len(running) != 1 {
		t.Fatalf("got %d running models, want 1", len(running))
	}

	got := running[0]
	if got.Name != "qwen3.5:9b" {
		t.Errorf("Name = %q, want qwen3.5:9b", got.Name)
	}
	// Captured on a machine with no CUDA GPU, so nothing is in VRAM. That is
	// exactly the case the benchmark has to make obvious.
	if got.SizeVRAM != 0 {
		t.Errorf("SizeVRAM = %d, want 0", got.SizeVRAM)
	}
	if got.OnGPU() != 0 {
		t.Errorf("OnGPU() = %v, want 0", got.OnGPU())
	}
	// The server reports its default window, not the model's maximum.
	if got.ContextLength != 4096 {
		t.Errorf("ContextLength = %d, want 4096", got.ContextLength)
	}
}

func TestOnGPUFraction(t *testing.T) {
	tests := []struct {
		name string
		m    llm.RunningModel
		want float64
	}{
		{name: "fully resident", m: llm.RunningModel{Size: 100, SizeVRAM: 100}, want: 1},
		{name: "partly offloaded", m: llm.RunningModel{Size: 100, SizeVRAM: 75}, want: 0.75},
		{name: "cpu only", m: llm.RunningModel{Size: 100, SizeVRAM: 0}, want: 0},
		{name: "nothing loaded", m: llm.RunningModel{}, want: 0},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := tt.m.OnGPU(); got != tt.want {
				t.Errorf("OnGPU() = %v, want %v", got, tt.want)
			}
		})
	}
}
