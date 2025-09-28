# Tool-Calling Benchmark Strategy

To evaluate LLM tool-calling capabilities we introduce a new family of tasks tagged with `tool_call`. These tasks bundle:

- **Mock tools** exposed as CLI binaries (Python scripts or shell wrappers) that print deterministic JSON/data.
- **Task code** that must invoke the tool via subprocess/function call, parse the response, and return structured results.
- **Unit tests** that assert both behaviour and the fact the tool was invoked (using spies/mocks or instrumented scripts that leave traces on disk/stdout).

## Evaluation Flow
1. Harness provisions the task workspace (mock tools are included inside the `workspace/tools/` directory).
2. The LLM patch must modify the target module so that it calls the tool script.
3. Tests execute the code; instrumentation inside the mock tool asserts it was called with the expected arguments and exits with non-zero status when misused.
4. Output parsing assertions ensure the model not only calls the tool but interprets the response correctly.

## Design Goals
- Zero external dependencies (tools run locally, offline).
- Deterministic outputs so that tests remain stable across runs.
- Cross-language coverage (Python CLI integration, Node.js tool invocation, etc.).

Upcoming tasks will follow this blueprint.
