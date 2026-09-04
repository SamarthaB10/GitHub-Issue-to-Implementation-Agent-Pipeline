# Wayfinding Map: Planner Control Plane and Provider-Neutral Worker Fleet

## Destination

Define the complete architecture and implementation route for a two-plane
system:

- LangGraph/API Planner agents deeply explore the repository and create a
  validated implementation plan.
- Chief receives the approved plan, converts it into dependency-aware tickets,
  and delegates those tickets to Codex or Claude Runtime workers.
- Runtime workers implement changes in isolated worktrees and return validated
  results and Skill traces.

The map is complete when the contracts and decisions are clear enough to
implement the full flow without separate cleanup, testing, or review agent
roles.

## Notes

- Domain: supervised AI software implementation.
- Human approval remains required before delegation.
- LangGraph is for issue analysis, repository exploration, planning, approval,
  and revision.
- Runtime workers are Codex or Claude processes, not API-agent or LangGraph
  nodes.
- Every worker receives `sub_agents.md`, `context.agent`, the available Skill
  catalog, and a required implementation process.
- Required Runtime process: `implement → tdd → code-review`.
- Planner agents receive scoped local repository tools and approved,
  read-only GitHub-native exploration tools.
- GitHub-native exploration is repository-scoped, ref-aware, bounded, and
  read-only. It must not create or change GitHub resources.
- Runtime workers receive only task-scoped local tools by default. Remote
  access is an explicit capability for a ticket, not a default worker power.
- No API keys or secrets may enter the repository or worker context.
- Consult the `wayfinder`, `grilling`, `domain-modeling`, `to-tickets`,
  `implement`, `tdd`, `code-review`, and `writing-for-agents` Skills during
  design and implementation.
- GitHub issue writes are currently unavailable, so this local Markdown
  directory is the active tracker.

## Decisions so far

The MVP resolves the map with these defaults:

- Planner handoffs use schema version 1 and require an approved ready plan plus
  a shared base commit.
- GitHub Planner tools use bounded GET requests scoped to one repository and
  optional ref. GitHub writes stay outside the Planner tool surface.
- Codex and Claude use the same `WorkerProcess` contract and differ only in
  their local CLI command adapter.
- Chief stores assignments, events, handoffs, and results in SQLite. Worker
  branches use isolated Git worktrees.
- Every Runtime worker receives `sub_agents.md` and `context.agent`, then must
  complete `implement → tdd → code-review` before Chief accepts its result.
- Final branch integration remains a human action.

## Not yet specified

- Provider process attach after an unexpected Chief restart.
- GitHub webhook ingestion and pull-request publication.
- Live streaming of provider stdout beyond bounded log files.
- Human-selected conflict resolution and final pull-request workflow.

## Out of scope

- Building a second LangGraph worker fleet.
- Creating separate cleanup, testing, or review agent roles.
- Storing provider credentials in the repository.
- Fully autonomous merge or release without human approval.
