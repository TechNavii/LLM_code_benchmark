# Go Toolchain Setup for Benchmark Verification

The Go tasks in this benchmark suite rely on the standard `go` toolchain for formatting (`gofmt`) and testing (`go test`). The current development environment does not ship with Go preinstalled, so you must install it locally (or in CI) before running the harness against Go tasks.

## Installation
1. Download the appropriate binary archive from [https://go.dev/dl/](https://go.dev/dl/).
2. Follow the official installation steps for your OS (for macOS and Linux, extract to `/usr/local/go`; for Windows, run the MSI).
3. Add the Go binary directory to your `PATH`:
   - macOS/Linux: `export PATH=$PATH:/usr/local/go/bin`
   - Windows PowerShell: `[Environment]::SetEnvironmentVariable("PATH", "$env:PATH;C:\\Go\\bin", "User")`
4. Confirm installation with `go version`.

## Verification Workflow
Once Go is available:
- Run `gofmt ./...` inside each Go task directory to ensure formatting matches the toolchain defaults.
- Execute `go test ./...` to reproduce the harness checks locally.
- The harness will automatically call `go test`, but having Go installed allows you to debug failures rapidly and keep reference patches compliant with gofmt.

If you are using CI, install Go in the job before invoking `python3 harness/run_harness.py` for tasks tagged with `go`.
