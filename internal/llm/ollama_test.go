package llm_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
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
	tests := []struct {
		name        string
		status      int
		body        string
		wantInError []string
	}{
		{
			name:        "json error body",
			status:      http.StatusNotFound,
			body:        `{"error":"model 'no-such-model:latest' not found"}`,
			wantInError: []string{"404", "no-such-model:latest", "not found"},
		},
		{
			// A mistyped path never reaches Ollama's handlers, so the body is
			// the HTTP mux's plain text rather than JSON.
			name:        "plain text error body",
			status:      http.StatusNotFound,
			body:        "404 page not found\n",
			wantInError: []string{"404", "page not found"},
		},
		{
			name:        "empty error body",
			status:      http.StatusInternalServerError,
			body:        "",
			wantInError: []string{"500"},
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
			for _, want := range tt.wantInError {
				if !strings.Contains(err.Error(), want) {
					t.Errorf("error %q, want it to mention %q", err, want)
				}
			}
		})
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
}

func TestNewAcceptsHostWithoutScheme(t *testing.T) {
	srv := serveFixture(t, "generate.json", nil)

	// OLLAMA_HOST is conventionally "host:port" with no scheme.
	hostPort := strings.TrimPrefix(srv.URL, "http://")

	if _, err := llm.New(hostPort, "m").Generate(llm.GenerateRequest{Prompt: "hi"}); err != nil {
		t.Fatalf("Generate against %q: %v", hostPort, err)
	}
}
