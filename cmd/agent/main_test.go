package main

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestRun(t *testing.T) {
	tests := []struct {
		name       string
		args       []string
		wantCode   int
		wantStdout string
		wantStderr string // substring; empty means stderr must be empty
	}{
		{
			name:       "no arguments",
			args:       nil,
			wantCode:   0,
			wantStdout: "quantic-agent: no tasks defined yet\n",
		},
		{
			name:       "version",
			args:       []string{"-version"},
			wantCode:   0,
			wantStdout: "quantic-agent dev\n",
		},
		{
			name:       "help",
			args:       []string{"-h"},
			wantCode:   0,
			wantStderr: "-version",
		},
		{
			name:       "unknown flag",
			args:       []string{"-publish"},
			wantCode:   2,
			wantStderr: "flag provided but not defined: -publish",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var stdout, stderr bytes.Buffer

			code := run(tt.args, &stdout, &stderr)

			if code != tt.wantCode {
				t.Errorf("exit code = %d, want %d", code, tt.wantCode)
			}
			if got := stdout.String(); got != tt.wantStdout {
				t.Errorf("stdout = %q, want %q", got, tt.wantStdout)
			}
			if tt.wantStderr == "" && stderr.Len() > 0 {
				t.Errorf("stderr = %q, want it empty", stderr.String())
			}
			if !strings.Contains(stderr.String(), tt.wantStderr) {
				t.Errorf("stderr = %q, want it to contain %q", stderr.String(), tt.wantStderr)
			}
		})
	}
}

func TestRunAsk(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"model":"quantic-9b:latest","response":"ok","done":true,` +
			`"done_reason":"stop","eval_count":2,"eval_duration":205098000}`))
	}))
	t.Cleanup(srv.Close)

	var stdout, stderr bytes.Buffer
	code := run([]string{"-ollama", srv.URL, "-ask", "Reply with exactly: ok"}, &stdout, &stderr)

	if code != 0 {
		t.Fatalf("exit code = %d, want 0 (stderr: %q)", code, stderr.String())
	}
	if got := stdout.String(); got != "ok\n" {
		t.Errorf("stdout = %q, want %q", got, "ok\n")
	}
	// The run line goes to stderr so that stdout stays pipeable.
	if got := stderr.String(); !strings.Contains(got, "2 tokens") {
		t.Errorf("stderr = %q, want it to report the token count", got)
	}
}

// checkServer answers the two endpoints -check calls.
func checkServer(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/version":
			w.Write([]byte(`{"version":"0.30.3"}`))
		case "/api/tags":
			w.Write([]byte(`{"models":[{"name":"qwen3.5:9b","size":6594474711,` +
				`"details":{"parameter_size":"9.7B","quantization_level":"Q4_K_M",` +
				`"context_length":262144},"capabilities":["completion","tools","thinking"]}]}`))
		default:
			t.Errorf("unexpected path %q", r.URL.Path)
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestRunCheck(t *testing.T) {
	srv := checkServer(t)

	var stdout, stderr bytes.Buffer
	code := run([]string{"-ollama", srv.URL, "-model", "qwen3.5:9b", "-check"}, &stdout, &stderr)

	if code != 0 {
		t.Fatalf("exit code = %d, want 0 (stderr: %q)", code, stderr.String())
	}
	got := stdout.String()
	for _, want := range []string{"ollama 0.30.3", "* qwen3.5:9b", "6.6 GB", "256K", "tools"} {
		if !strings.Contains(got, want) {
			t.Errorf("stdout = %q, want it to contain %q", got, want)
		}
	}
}

func TestRunCheckFlagsAMissingModel(t *testing.T) {
	srv := checkServer(t)

	var stdout, stderr bytes.Buffer
	code := run([]string{"-ollama", srv.URL, "-model", "not-pulled:latest", "-check"}, &stdout, &stderr)

	// A model that was never pulled on the target machine has to fail here,
	// not later in the middle of a task.
	if code != 1 {
		t.Errorf("exit code = %d, want 1", code)
	}
	if got := stderr.String(); !strings.Contains(got, "not-pulled:latest is not on this server") {
		t.Errorf("stderr = %q, want it to name the missing model", got)
	}
}

func TestRunReportsAnUnreachableServer(t *testing.T) {
	// A server that is closed before the call: its port is guaranteed to be
	// one nothing is listening on.
	srv := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	deadURL := srv.URL
	srv.Close()

	var stdout, stderr bytes.Buffer
	code := run([]string{"-ollama", deadURL, "-ask", "hi"}, &stdout, &stderr)

	if code != 1 {
		t.Errorf("exit code = %d, want 1", code)
	}
	if stdout.Len() > 0 {
		t.Errorf("stdout = %q, want it empty on failure", stdout.String())
	}
	if got := stderr.String(); !strings.HasPrefix(got, "agent:") {
		t.Errorf("stderr = %q, want it to start with the program name", got)
	}
}

// Ollama resolves model names case-insensitively, so -check must too, or it
// reports a perfectly usable model as missing.
func TestRunCheckMatchesModelNamesCaseInsensitively(t *testing.T) {
	srv := checkServer(t)

	var stdout, stderr bytes.Buffer
	code := run([]string{"-ollama", srv.URL, "-model", "QWEN3.5:9B", "-check"}, &stdout, &stderr)

	if code != 0 {
		t.Fatalf("exit code = %d, want 0 (stderr: %q)", code, stderr.String())
	}
	if got := stdout.String(); !strings.Contains(got, "* qwen3.5:9b") {
		t.Errorf("stdout = %q, want the model marked as selected", got)
	}
}
