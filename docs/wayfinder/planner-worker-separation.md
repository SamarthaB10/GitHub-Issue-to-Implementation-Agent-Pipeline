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

None. The human has confirmed the core separation, but no decision ticket has
been resolved yet.

## Not yet specified

- Exact Planner-to-Chief artifact and version boundary.
- Exact least-privilege GitHub exploration tool set and how Planner access is
  authenticated and scoped.
- Provider-neutral launch contract for Codex and Claude.
- Worker process lifecycle, isolation, timeout, cancellation, and recovery.
- How live worker output and Skill traces reach Chief.
- How Chief validates scope, checks, commits, and dependencies.
- API and CLI entrypoints for Planner runs, approval, delegation, and results.
- How final worker commits become a human-reviewed integration or pull request.

## Out of scope

- Building a second LangGraph worker fleet.
- Creating separate cleanup, testing, or review agent roles.
- Storing provider credentials in the repository.
- Fully autonomous merge or release without human approval.

