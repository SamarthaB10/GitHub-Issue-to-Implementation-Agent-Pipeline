---
status: accepted
---

# Chief terminal session lifecycle

Chief will be operated from a project-local terminal command with separate
start, resume, status, logs, and stop actions. A stopped or interrupted session
must preserve the run state, logs, worker branches, and worktrees so the user
can resume it later; cleanup remains a separate explicit user action. The
initial issue input will come from a local issue file, which keeps the first
runtime independent of GitHub API authentication.
