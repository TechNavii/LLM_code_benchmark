# Python Expert Task: Workflow Scheduler

Your team operates a workflow engine that schedules data processing jobs. Each job declares its dependencies and runtime in seconds. You must compute a deterministic execution plan that honours all dependencies, surfaces invalid graphs, and exposes timing metadata used by the orchestrator.

Implement `compute_schedule(definitions: Sequence[Mapping[str, Any]]) -> Dict[str, Any]` in `workspace/workflow.py` with the following behaviour:

- `definitions` is an iterable of dictionaries. Every dictionary contains:
  - `id`: a unique string identifier.
  - `duration`: a positive integer runtime in seconds.
  - `deps`: an iterable of zero or more task ids that **must finish** before this task starts.
- Build a directed acyclic graph from the definitions. If a dependency references an unknown task id, raise a `KeyError` with that id.
- Detect dependency cycles. If a cycle exists, raise `ValueError` with a message that contains the word `cycle`.
- Produce a deterministic topological order that breaks ties lexicographically by task id.
- For each task compute:
  - `start`: the earliest second it can start (the maximum finish time of all dependencies, or 0 if none).
  - `finish`: `start + duration`.
- Return a dictionary with four keys:
  - `order`: the ordered list of task ids.
  - `start_times`: mapping task id → start time.
  - `finish_times`: mapping task id → finish time.
  - `total_duration`: finish time of the last task (the makespan).

The implementation must be linearithmic at worst (`O(n log n + e)`), handle deeply nested dependency chains, and leave the input untouched.

The provided tests cover:
- Validation of missing dependencies and cycles.
- Tie-breaking between independent tasks.
- Timing calculations for branched dependency graphs.
- Stability across large collections with many shared prerequisites.
