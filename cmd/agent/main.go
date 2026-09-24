// Command agent is the quantic-agent daemon.
//
// It still has no scheduled tasks. What it can do as of milestone 2 is reach
// the local model server: -check reports the server version, -ask sends one
// prompt and prints the reply.
package main

import (
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

// defaultModel is the model chosen for the target hardware (design §4): the
// largest Qwen that fits entirely in 16GB of VRAM with room left for a long
// context. Development happens on a different machine, so both flags below
// read an environment variable first and nothing is baked in.
const defaultModel = "qwen3.5:9b"

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
		if err == flag.ErrHelp {
			return 0
		}
		return 2
	}

	if *showVersion {
		fmt.Fprintln(stdout, "quantic-agent", version)
		return 0
	}

	client := llm.New(*baseURL, *model)

	switch {
	case *check:
		serverVersion, err := client.Version()
		if err != nil {
			fmt.Fprintln(stderr, "agent:", err)
			return 1
		}
		fmt.Fprintf(stdout, "ollama %s at %s\n", serverVersion, *baseURL)

		models, err := client.Models()
		if err != nil {
			fmt.Fprintln(stderr, "agent:", err)
			return 1
		}
		selected := false
		for _, m := range models {
			marker := " "
			if m.Name == client.Model() {
				marker, selected = "*", true
			}
			fmt.Fprintf(stdout, "%s %-26s %5.1f GB  %-6s %-7s ctx %-5s %s\n",
				marker, m.Name, float64(m.Size)/1e9, m.Details.ParameterSize,
				m.Details.QuantizationLevel, shortCount(m.Details.ContextLength),
				strings.Join(m.Capabilities, " "))
		}
		// The agent runs where its developer isn't sitting, so a model that
		// was never pulled has to be loud now rather than 404 mid-task.
		if !selected {
			fmt.Fprintf(stderr, "agent: %s is not on this server\n", client.Model())
			return 1
		}
		return 0

	case *ask != "":
		// Thinking is suppressed: the agent wants the answer, and a
		// reasoning trace is text nothing downstream is allowed to publish.
		resp, err := client.Generate(llm.GenerateRequest{Prompt: *ask, Think: llm.Bool(false)})
		if err != nil {
			fmt.Fprintln(stderr, "agent:", err)
			return 1
		}
		fmt.Fprintln(stdout, resp.Response)
		fmt.Fprintf(stderr, "%s · %d tokens · %s%s\n",
			resp.Model, resp.EvalCount, resp.EvalDuration.Round(time.Millisecond), truncationNote(resp))
		return 0
	}

	fmt.Fprintln(stdout, "quantic-agent: no tasks defined yet")
	return 0
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
