# Instructions for coding agents

## Project purpose

This repository contains a GitHub issue-to-implementation planning service. It
turns an issue into a structured brief, maps the relevant repository code,
creates an implementation plan, and pauses for human approval then exectues the plan.

Keep the human approval boundary intact: an implementation plan must reach the
`plan_approval` node before the workflow can finish as `plan_approved`.

## Work sequence

Use this sequence for every change:

1. Read the relevant source, prompt, schema, and unit-test files before editing.
   The change is understood when every affected module and its test seam are
   identified.
2. Preserve the artifact flow: `IssueInput` → `IssueBrief` → `RepositoryMap`
   → `ImplementationPlan` → `PlanApprovalDecision`. A new field or status is
   complete only when every producer, consumer, serializer, and test that uses
   it is updated.
3. Make the smallest change that satisfies the request. Keep repository facts
   in repository exploration and keep issue facts in issue analysis.
4. Add or update deterministic tests for the changed behavior. The change is
   ready when the relevant tests cover success, invalid input, and the affected
   route or boundary.
5. Run the test and lint commands in this file. The change is verified when
   each available check has a recorded result and any unavailable check has a
   clear environment reason.

## Repository map

- `src/api/` is the FastAPI control plane. `app.py` creates the application and
  injects `RunService`; `routes.py` exposes health, run start, run inspection,
  and plan-decision endpoints; `service.py` owns thread IDs, in-process thread
  tracking, per-thread decision locks, and graph snapshots.
- `src/agents/graph/` defines the LangGraph contract. `workflow.py` builds the
  graph; `routing.py` contains conditional route decisions; `approvals.py`
  validates the human interrupt; `state.py` defines the shared state shape.
- `src/agents/issue_analyst.py` loads the issue-analysis prompt and few-shot
  examples, calls the structured model, and writes `issue_brief` plus the next
  status.
- `src/agents/repo_explorer.py` creates a repository-scoped tool agent. It
  gathers evidence and validates the result as `RepositoryMap`.
- `src/agents/implementer.py` is the implementation planner. Despite its file
  name, it is read-only and produces `ImplementationPlan` artifacts.
- `src/agents/tools/` contains bounded, read-only repository tools.
  `repository_tools.py` handles files, text search, project context, and Git
  history. `python_tools.py` reports Python AST structure without importing or
  executing repository code.
- `src/agents/skill_catalog.py` prepares `sub_agents.md` and `context.agent`
  for each Chief-created Runtime worker.
- `src/agents/worker_queue.py` writes append-only Chief ticket entries to the
  authoritative and worker-local queues.
- `src/agents/worker_protocol.py` checks the required `implement`, `tdd`, and
  `code-review` Skill trace before Chief accepts a WorkerResult.
- `src/agents/tools/runtime_tools.py` provides guarded Runtime worker edits,
  approved checks, and Worker branch commits.
- `src/agents/shared.py` loads and caches prompt files. It rejects absolute
  paths and paths that escape `src/prompts`.
- `src/schemas/` contains the Pydantic v2 boundaries for issue, repository,
  planning, approval, and API data. Models use `extra="forbid"`.
- `src/prompts/` contains model instructions. The three prompt groups are
  `issue_analyst`, `repository_explorer`, and `implementation_planner`.
- `tests/unit/` contains offline tests for the API, graph, nodes, schemas,
  prompts, and repository tools.

## Workflow contract

`build_workflow()` creates these nodes and edges:

```text
START
  → issue_analyst
  → repository_explorer       if IssueBrief.is_actionable
  → implementation_planner
  → plan_approval             if ready_for_approval
  → END                       after approve or cancel
```

The graph ends with `needs_clarification` when the issue is not actionable or
the plan has blocking questions. A `request_changes` decision stores
`plan_feedback`, runs the planner again, and pauses for approval again.

Important statuses are:

- `ready_for_exploration`
- `repository_explored`
- `ready_for_plan_review`
- `needs_clarification`
- `plan_revision_requested`
- `plan_approved`
- `cancelled`

The default checkpointer is `InMemorySaver`. It supports resume while the
server process remains alive. `RunService` also keeps known thread IDs in
memory, so a process restart loses both workflow state and API thread lookup.
Use a custom checkpointer only when the caller supplies one to
`build_workflow(checkpointer=...)`.

## Engineering rules

- Use Python 3.11+ syntax and Pydantic v2 APIs such as `model_validate`,
  `model_dump`, and `model_dump_json`.
- Keep node functions async when they call a model or graph service. Return a
  partial state dictionary; let LangGraph merge it into the shared state.
- Validate every model-produced artifact at its boundary. Update the Pydantic
  schema and its validation tests together.
- Keep prompts in `src/prompts/`. Load them through `load_prompt`; keep few-shot
  data in the matching prompt directory.
- Read [`docs/skills/INDEX.md`](docs/skills/INDEX.md) before changing the agent
  instruction system. Every Chief-created sub-agent receives `sub_agents.md`
  and `context.agent`; use the project snapshots listed in that catalog.
- Chief uses `to-tickets` to turn an approved plan into WorkerTask queue
  entries. Every Runtime worker follows `implement → tdd → code-review` and
  reports Skill traces that Chief can verify.
- Ground planner file and symbol references in the `RepositoryMap`. Ground
  explorer claims in tool output. Keep assumptions, open questions, risks, and
  acceptance criteria explicit in the appropriate schema fields.
- Treat `src/agents/tools/` as a least-privilege surface. Resolve all
  model-provided paths under the approved repository root, exclude `.git`, use
  fixed subprocess argument lists, use `shell=False` behavior, and keep output,
  file size, line count, batch size, and command time bounded.
- Keep repository tools read-only. Use `rg` for discovery and literal search,
  `git` only for branch/status/history inspection, and AST parsing for Python
  structure. The tools must not execute repository code.
- Keep API validation at the request boundary. `repository_path` must resolve
  to an existing absolute directory. Preserve `404` for unknown runs, `409`
  for decisions submitted when no approval is pending, and `422` for invalid
  request or decision data.
- Keep model calls deterministic where possible: the current agents use
  `temperature=0`, bounded timeouts, and limited retries.
- Keep tests offline. Patch node functions, chain builders, or graph services
  with fakes instead of making live OpenAI calls.
- Keep secrets in local environment files. Use `OPENAI_API_KEY` and
  `OPENAI_MODEL`; keep `.env` files uncommitted.
- Update `README.md` when an externally visible endpoint, setup step, workflow
  status, limitation, or roadmap item changes.

## Test seams

Use the existing tests as the pattern for new coverage:

- `test_workflow.py` patches graph nodes and checks routing, interrupts,
  revision loops, cancellation, completion, and checkpointer behavior.
- `test_api.py` builds an app with `create_app(RunService(graph))` and uses
  FastAPI `TestClient` with fake graph nodes.
- `test_implementation_planner.py` uses a fake chain and checks prompt inputs,
  required artifacts, status mapping, and plan validation.
- `test_issue_analyst.py` checks prompt message order and validates the two
  few-shot JSON examples as `IssueBrief` values.
- `test_repository_tools.py` creates a temporary Git repository and checks
  bounded reads, path escape protection, context discovery, and AST parsing.

When changing a route, update route tests and the relevant routing tests. When
changing a schema, test both the valid shape and rejected extra or invalid
fields. When changing a tool limit or safety rule, add a focused regression
test in `test_repository_tools.py`.

## Commands

Create and activate the documented environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Run the full checks from the repository root:

```bash
PYTHONPATH=src python -m pytest -q
ruff check src tests
```

Start the API locally with:

```bash
PYTHONPATH=src uvicorn api.app:app --reload
```

Use `/health` for a quick service check and `/docs` for the OpenAPI interface.

## Scope boundary

The Runtime worker foundation is being added in stages. Worktree guards, queue
records, skill contexts, bounded edits, checks, and Skill trace validation are
separate capabilities with separate safety tests. Do not imply that the
current planner already starts a complete implementation Fleet until Chief
launch and recovery are implemented.
