# Agent Delivery Context

This context defines the roles and Git boundaries for the issue-to-implementation
agent pipeline.

## Roles

**Design-time agent**:
An agent that builds or changes the GH-Pipeline system itself. It may edit the
current project workspace, run development checks, and update project
documentation when the user requests that work.

**Chief**:
The supervisor that communicates with the user and controls delegation. Chief
receives the planner's approved artifacts, assigns bounded tasks, starts and
stops workers, monitors errors, reviews diffs and test results, and asks the
user for decisions. Chief has no source-edit capability and does not integrate
changes into `main`.

**Planner agent**:
A LangGraph/API-backed planning agent that deeply explores a repository and
creates a validated issue brief, repository map, or implementation plan. A
Planner agent is read-only. It may use local repository tools and approved
read-only GitHub-native exploration tools. It does not implement code or run as
a Runtime worker.

**Planner graph**:
The LangGraph control-plane workflow that runs Planner agents for issue
analysis, repository exploration, implementation planning, human approval, and
plan revision. It produces the artifacts that Chief uses for delegation.

**Planner handoff**:
The versioned `PlannerHandoff` artifact containing the approved issue brief,
repository map, implementation plan, approval decision, repository path, and
shared base commit. Chief accepts only schema version 1 handoffs with an
approved, ready plan.

**Worker**:
A sub-agent assigned one bounded task by Chief. A worker may read repository
evidence, edit files, run checks, and commit changes only on its own worker
branch and worktree.

**Runtime worker**:
A Codex or Claude process launched by Chief during a supervised run. It is not
an API agent or a LangGraph node. Its current directory is its assigned
worktree, not the Chief project workspace.

**Provider worker**:
A Runtime worker started through a provider adapter for Codex or Claude. The
provider changes the launch mechanism, but not the WorkerTask, safety rules,
required Skill process, or WorkerResult contract.

**User**:
The human authority for approval and integration. The user selects or combines
worker results and creates the final merge or commit on `main`.

**Fleet**:
The set of workers active for one Chief-supervised run. Fleet members work in
parallel when their task dependencies allow it.

## Git isolation

**Main**:
The protected integration branch. Only the user may merge to or commit code on
`main`.

**Worktree**:
An isolated checkout assigned to exactly one worker. Each worktree starts from
the same recorded base commit and has a unique worker branch.

**Worker branch**:
A temporary branch owned by one worker for one task. Chief may inspect and test
the branch, but Chief does not merge, cherry-pick, or commit it to `main`.

**Integration**:
The user-controlled action that brings selected worker changes into `main`.
Conflict resolution and final commit authority remain with the user.

**Supervision**:
Chief's responsibility to track worker state, errors, diffs, tests, overlap, and
rework until the run reaches a user decision or a terminal state.

**Project workspace**:
A user-owned checkout from which the terminal conversation with Chief is
started and resumed for that project.

**Chief conversation**:
The ongoing user interaction with Chief that carries the project request,
decisions, worker progress, and final integration handoff across terminal
sessions.

**Chief session**:
One attached terminal session in which Chief supervises a run for a project
workspace. A session can stop and resume, and only one session may be active for
one project workspace at a time.

**Run**:
One supervised implementation effort for one issue, from its start through a
user decision or another terminal state.

**Chief state store**:
The durable SQL record of a run, its workers, tasks, decisions, results, and
recovery information.

**Event record**:
An immutable record of one state change in a run, kept so Chief can explain and
recover its supervision history.

**Task graph**:
A set of work tasks connected by prerequisites. A task starts when its required
inputs are ready; tasks without shared prerequisites may run in parallel.

**Fan-out**:
The point where Chief creates multiple independent worker tasks from one
approved plan.

**Fan-in**:
The point where Chief collects worker results, checks overlap and quality, and
prepares one integration handoff for the user.

**WorkerTask**:
The vertical-slice ticket and complete assignment for one worker, including its
goal, dependencies, acceptance criteria, assigned scope, required checks, base
commit, branch, Worktree, and required skill route.

**WorkerResult**:
The worker's committed branch, clean-worktree confirmation, check results, diff
summary, and any errors or unresolved questions.

**Retry**:
A bounded attempt to run a failed worker task again in a fresh worktree. A
changed scope or repeated failure requires a user decision.

**Cleanup**:
The explicit user-authorized removal of a worker worktree or branch after its
result is selected, integrated, or discarded.

**Protected main**:
The rule that only the user's Git identity may integrate or commit code on the
`main` branch.

**Approval gate**:
A user decision that permits the next high-impact stage, beginning with the
implementation fleet after the plan is ready.

**Shared base commit**:
The single recorded commit from which all workers in one implementation fleet
start. Completed worker branches do not silently become another worker's base.

**Sub-agent queue**:
The ordered work channel for one worker. Chief places assigned tasks and
worker-specific change requests in it; that worker reads and pulls only its own
entries.

**Queue entry**:
One task or change request in a sub-agent queue, with enough context for the
assigned worker to act and report its result.

**Worker skill protocol**:
The required implementation practice for a worker: use test-first work for
behavior changes, follow the implementation lifecycle, use UI engineering rules
for user-facing UI, and complete code review before reporting success.

**Worker-qualified queue ID**:
The identity of one queue entry. It includes the worker identity and is unique
across every worker queue in the run.

**Workflow priority**:
The priority for a regular workflow request.

**Error-detection priority**:
The priority for detecting or correcting a bug in an existing feature.

**Immediate priority**:
The priority for an extreme-importance task that Chief must handle before lower
priority queue entries.

**Skill catalog**:
The project-local index of skills that Chief may route to workers.

**Skill snapshot**:
A reviewed, portable copy of a skill and its supporting files stored with the
project. It changes only after an explicit refresh.

**Skill route**:
The rule that selects the skills available to one agent. Planner agents follow
the skills invoked during human discussion. Every Runtime worker has the
required implementation route `implement → tdd → code-review`, plus
conditional skills.

**GitHub exploration tool set**:
The least-privilege, read-only GitHub-native capabilities available to Planner
agents for remote issues, pull requests, files, commits, branches, checks, and
repository metadata. These tools are scoped to the target repository and do
not create issues, comments, branches, commits, or pull requests.

**Chief tool**:
A structured capability that lets Chief supervise, inspect, and record a run
without editing source or integrating Git changes.

**Worker tool**:
A structured capability that lets one worker inspect and change only its
assigned worktree, run approved checks, and commit only on its assigned branch.

**Assigned scope**:
The files, symbols, and checks that one WorkerTask authorizes for one Runtime
worker. A Runtime worker must treat all other product paths as outside its
task.

**Skill trace**:
Structured evidence from a Runtime worker that records the required skill
phases and their evidence for Chief to verify.

**Sub-agent context bundle**:
The `sub_agents.md` rules file and `context.agent` context file that Chief
provides to every sub-agent before it starts.

**Integration report**:
The structured summary Chief gives the user after it accepts WorkerResults. It
lists worker commits, changed files, overlaps, errors, and the next human
action. It never performs a merge.

**Provider adapter**:
The small boundary that converts a Codex or Claude CLI choice into a common
Runtime worker launch. It receives no repository secret and does not alter the
WorkerTask or Skill protocol.
