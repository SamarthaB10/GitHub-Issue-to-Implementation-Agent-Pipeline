---
status: accepted
---

# Chief-supervised parallel worker isolation

The pipeline will expose one user-facing orchestrator, Chief, and execute
implementation tasks through parallel workers in separate Git worktrees created
from one recorded base commit. Workers may commit only to their own branches;
Chief may supervise, inspect, test, and request rework, but only the user may
integrate or commit code on `main`. This gives independent workers safe write
scope and preserves a clear human-controlled integration boundary, with the
trade-off that overlapping changes require rework or user-led conflict
resolution.
