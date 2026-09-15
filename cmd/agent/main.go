// Command agent is the quantic-agent daemon.
//
// At milestone 1 it has no tasks to run. It exists so the module produces a
// binary and the cmd/ + internal/ layout is real rather than described.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
)

// version is replaced at build time with -ldflags once there are releases
// (milestone 13). Until then every build reports "dev".
var version = "dev"

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

	fmt.Fprintln(stdout, "quantic-agent: no tasks defined yet")
	return 0
}
