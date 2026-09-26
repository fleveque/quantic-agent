// Command agent is the quantic-agent daemon.
//
// It still has no scheduled tasks. What it can do so far is reach the local
// model server: -check reports the server version and its models, -ask sends
// one prompt and prints the reply.
//
// Exit status: 0 success, 1 failure, 2 wrong usage, 3 the model server wasn't
// there to answer. 3 means nothing was attempted, so a scheduler can simply
// run the same command again later (design §3.6).
package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/fleveque/quantic-agent/internal/llm"
)

// version is replaced at build time with -ldflags once there are releases
// (milestone 13). Until then every build reports "dev".
var version = "dev"

// defaultModel is the safe choice for the target hardware (design §4): it fits
// any 16GB card with room to spare. The primary candidate, Qwen3.8-27B at
// about 3.5 bits per weight, replaces it once cmd/bench confirms it on the
// real card. Development happens on a different machine, so both flags below
// read an environment variable first and nothing is baked in.
const defaultModel = "qwen3.5:9b"

// Exit codes, as documented at the top of this file.
const (
	exitOK          = 0
	exitFailed      = 1
	exitUsage       = 2
	exitUnavailable = 3
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

// run is main with its dependencies passed in, returning the exit code.
//
// main itself is hard to test: it reads the real process arguments, writes to
// the real terminal, and os.Exit skips deferred calls. So main stays one line
// and everything worth testing lives here.
func run(args []string, stdout, stderr io.Writer) int {
	fs := flag.NewFlagSet("agent", flag.ContinueOnError)
	fs.SetOutput(stderr)
	showVersion := fs.Bool("version", false, "print the version and exit")
	check := fs.Bool("check", false, "report the model server's version and exit")
	ask := fs.String("ask", "", "send one prompt to the model and print the reply")
	baseURL := fs.String("ollama", envOr("OLLAMA_HOST", llm.DefaultBaseURL), "model server base URL")
	model := fs.String("model", envOr("QUANTIC_MODEL", defaultModel), "model to generate with")

	if err := fs.Parse(args); err != nil {
		// The flag package has already written the problem and the usage
		// text to stderr. -h is a request, not a mistake.
		if errors.Is(err, flag.ErrHelp) {
			return exitOK
		}
		return exitUsage
	}

	if *showVersion {
		fmt.Fprintln(stdout, "quantic-agent", version)
		return exitOK
	}

	client := llm.New(*baseURL, *model)

	switch {
	case *check:
		serverVersion, err := client.Version()
		if err != nil {
			return fail(stderr, err, *baseURL, client.Model())
		}
		fmt.Fprintf(stdout, "ollama %s at %s\n", serverVersion, *baseURL)

		models, err := client.Models()
		if err != nil {
			return fail(stderr, err, *baseURL, client.Model())
		}
		selected := false
		for _, m := range models {
			marker := " "
			if strings.EqualFold(m.Name, client.Model()) {
				marker, selected = "*", true
			}
			fmt.Fprintf(stdout, "%s %-26s %5.1f GB  %-6s %-7s ctx %-5s %s\n",
				marker, m.Name, float64(m.Size)/1e9, m.Details.ParameterSize,
				m.Details.QuantizationLevel, shortCount(m.Details.ContextLength),
				strings.Join(m.Capabilities, " "))
		}
		// The agent runs where its developer isn't sitting, so a model that
		// was never pulled has to be loud now rather than 404 mid-task. Names
		// compare case-insensitively because that is how Ollama resolves them.
		if !selected {
			return fail(stderr, llm.ErrModelNotFound, *baseURL, client.Model())
		}
		return exitOK

	case *ask != "":
		// Thinking is suppressed: the agent wants the answer, and a
		// reasoning trace is text nothing downstream is allowed to publish.
		resp, err := client.Generate(llm.GenerateRequest{Prompt: *ask, Think: llm.Bool(false)})
		if err != nil {
			return fail(stderr, err, *baseURL, client.Model())
		}
		fmt.Fprintln(stdout, resp.Response)
		fmt.Fprintf(stderr, "%s · %d tokens · %s%s\n",
			resp.Model, resp.EvalCount, resp.EvalDuration.Round(time.Millisecond), truncationNote(resp))
		return exitOK
	}

	fmt.Fprintln(stdout, "quantic-agent: no tasks defined yet")
	return exitOK
}

// fail reports err and chooses the exit code. It decides by the kind of
// error, which the llm package exposes as values, never by matching the
// message text: messages are for people and can change.
func fail(stderr io.Writer, err error, baseURL, model string) int {
	switch {
	case errors.Is(err, llm.ErrUnavailable):
		fmt.Fprintf(stderr, "agent: no model server answering at %s. Is Ollama running?\n", baseURL)
		fmt.Fprintln(stderr, "agent:", err)
		return exitUnavailable

	case errors.Is(err, llm.ErrModelNotFound):
		fmt.Fprintf(stderr, "agent: %s is not on this server. Pull it with: ollama pull %s\n", model, model)
		return exitFailed
	}

	fmt.Fprintln(stderr, "agent:", err)

	// A 5xx means the server itself failed, such as a model that couldn't be
	// loaded. The reason is in its log, not in the reply.
	var apiErr *llm.APIError
	if errors.As(err, &apiErr) && apiErr.StatusCode >= 500 {
		fmt.Fprintln(stderr, "agent: the model server failed; its log has the cause (journalctl -u ollama)")
	}
	return exitFailed
}

// shortCount renders a context length the way model cards do: 262144 as 256K.
func shortCount(n int) string {
	switch {
	case n >= 1024*1024:
		return fmt.Sprintf("%dM", n/(1024*1024))
	case n >= 1024:
		return fmt.Sprintf("%dK", n/1024)
	default:
		return strconv.Itoa(n)
	}
}

func truncationNote(resp llm.GenerateResponse) string {
	if resp.Truncated() {
		return " · truncated: hit the token limit"
	}
	return ""
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
