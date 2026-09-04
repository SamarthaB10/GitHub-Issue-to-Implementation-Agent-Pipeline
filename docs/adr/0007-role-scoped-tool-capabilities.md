---
status: accepted
---

# Role-scoped runtime tool capabilities

Runtime Chief and runtime workers will receive separate structured tool
interfaces. These limits apply to the product runtime, not to design-time
agents that build the GH-Pipeline system itself. Runtime Chief may
supervise, inspect, run bounded checks, and record state, but has no source-edit
or Git-integration capability. Runtime workers may edit and commit only in
their assigned worktree and branch. General shell access, remote Git mutation,
and network access are excluded by default. Runtime file changes use
hash-checked patch operations, and Runtime checks use exact argument lists with
bounded time, output, and environment.
