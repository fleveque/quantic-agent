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
	"time"

	"github.com/fleveque/quantic-agent/internal/llm"
)

// version is replaced at build time with -ldflags once there are releases
// (milestone 13). Until then every build reports "dev".
var version = "dev"

// defaultModel is what runs on this machine today. Both flags below take an
// environment variable first, so nothing here is baked into the binary.
const defaultModel = "quantic-9b:latest"

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
		fmt.Fprintf(stdout, "ollama %s at %s, model %s\n", serverVersion, *baseURL, client.Model())
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
