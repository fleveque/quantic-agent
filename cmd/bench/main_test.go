package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
)

// benchServer answers the four endpoints a benchmark run touches, with
// numbers chosen so the reported rates are exact: 2000 prompt tokens in
// 0.5s is 4000 tok/s, 100 generated tokens in 2s is 50 tok/s.
func benchServer(t *testing.T, onGPU bool) *httptest.Server {
	t.Helper()
	vram := 0
	if onGPU {
		vram = 6222564555
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/tags":
			w.Write([]byte(`{"models":[{"name":"qwen3.5:9b","size":6594474711,` +
				`"details":{"parameter_size":"9.7B","quantization_level":"Q4_K_M"},` +
				`"capabilities":["completion","tools"]}]}`))
		case "/api/generate":
			w.Write([]byte(`{"model":"qwen3.5:9b","response":"done","done":true,` +
				`"done_reason":"stop","prompt_eval_count":2000,"prompt_eval_duration":500000000,` +
				`"eval_count":100,"eval_duration":2000000000,"total_duration":2500000000,` +
				`"load_duration":1000000000}`))
		case "/api/ps":
			w.Write([]byte(`{"models":[{"name":"qwen3.5:9b","size":6222564555,` +
				`"size_vram":` + strconv.Itoa(vram) + `,"context_length":4096}]}`))
		default:
			t.Errorf("unexpected path %q", r.URL.Path)
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestRunTable(t *testing.T) {
	srv := benchServer(t, true)

	var stdout, stderr bytes.Buffer
	code := run([]string{"-ollama", srv.URL, "-models", "qwen3.5:9b", "-contexts", "4096", "-predict", "100"}, &stdout, &stderr)

	if code != 0 {
		t.Fatalf("exit code = %d, want 0 (stderr: %q)", code, stderr.String())
	}
	got := stdout.String()
	for _, want := range []string{"qwen3.5:9b", "4K", "4000", "50.0", "100%"} {
		if !strings.Contains(got, want) {
			t.Errorf("table = %q, want it to contain %q", got, want)
		}
	}
}

func TestRunReportsCPUFallback(t *testing.T) {
	srv := benchServer(t, false)

	var stdout, stderr bytes.Buffer
	code := run([]string{"-ollama", srv.URL, "-models", "qwen3.5:9b", "-contexts", "4096"}, &stdout, &stderr)

	if code != 0 {
		t.Fatalf("exit code = %d, want 0 (stderr: %q)", code, stderr.String())
	}
	// A model that isn't on the GPU is the single most important thing this
	// tool can tell you, so it must be unmissable.
	if got := stdout.String(); !strings.Contains(got, "0% (CPU)") {
		t.Errorf("table = %q, want it to flag CPU execution", got)
	}
}

func TestRunJSON(t *testing.T) {
	srv := benchServer(t, true)

	var stdout, stderr bytes.Buffer
	code := run([]string{"-ollama", srv.URL, "-models", "qwen3.5:9b", "-contexts", "4096", "-json"}, &stdout, &stderr)

	if code != 0 {
		t.Fatalf("exit code = %d, want 0 (stderr: %q)", code, stderr.String())
	}

	var results []result
	if err := json.Unmarshal(stdout.Bytes(), &results); err != nil {
		t.Fatalf("decoding output: %v\n%s", err, stdout.String())
	}
	if len(results) != 1 {
		t.Fatalf("got %d results, want 1", len(results))
	}
	got := results[0]
	if got.PromptRate != 4000 {
		t.Errorf("PromptRate = %v, want 4000", got.PromptRate)
	}
	if got.GenRate != 50 {
		t.Errorf("GenRate = %v, want 50", got.GenRate)
	}
	if got.OnGPU != 1 {
		t.Errorf("OnGPU = %v, want 1", got.OnGPU)
	}
	if got.LoadSeconds != 1 {
		t.Errorf("LoadSeconds = %v, want 1", got.LoadSeconds)
	}
}

func TestRunSkipsModelsThatArentPulled(t *testing.T) {
	srv := benchServer(t, true)

	var stdout, stderr bytes.Buffer
	code := run([]string{"-ollama", srv.URL, "-models", "not-pulled:latest", "-contexts", "4096"}, &stdout, &stderr)

	if code != 1 {
		t.Errorf("exit code = %d, want 1", code)
	}
	if got := stderr.String(); !strings.Contains(got, "not-pulled:latest is not on this server") {
		t.Errorf("stderr = %q, want it to name the missing model", got)
	}
}

func TestParseSizes(t *testing.T) {
	tests := []struct {
		name    string
		in      string
		want    []int
		wantErr bool
	}{
		{name: "one", in: "4096", want: []int{4096}},
		{name: "several with spaces", in: "4096, 32768", want: []int{4096, 32768}},
		{name: "not a number", in: "4096,big", wantErr: true},
		{name: "zero", in: "0", wantErr: true},
		{name: "empty", in: "", wantErr: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := parseSizes(tt.in)
			if tt.wantErr {
				if err == nil {
					t.Fatalf("parseSizes(%q) = %v, want an error", tt.in, got)
				}
				return
			}
			if err != nil {
				t.Fatalf("parseSizes(%q): %v", tt.in, err)
			}
			if len(got) != len(tt.want) {
				t.Fatalf("parseSizes(%q) = %v, want %v", tt.in, got, tt.want)
			}
			for i := range got {
				if got[i] != tt.want[i] {
					t.Errorf("parseSizes(%q)[%d] = %d, want %d", tt.in, i, got[i], tt.want[i])
				}
			}
		})
	}
}
