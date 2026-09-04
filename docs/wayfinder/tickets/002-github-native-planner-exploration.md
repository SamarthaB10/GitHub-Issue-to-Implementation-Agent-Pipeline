# GitHub-Native Planner Exploration Surface

## Question

Which read-only GitHub-native capabilities should Planner agents receive?

Candidate capabilities:

- Repository metadata, default branch, rulesets, and branch-protection reads.
- File and directory fetches at a pinned ref.
- Code search scoped to the target repository and ref.
- Issue metadata, bodies, comments, and search.
- Pull request metadata, diffs, changed files, comments, and reviews.
- Commit details, history, compare, and status reads.
- Branch and ref reads.
- Workflow, check-run, job-step, log, and artifact metadata reads.

Decide least privilege, repository and ref scoping, pagination and output
limits, rate-limit handling, cache policy, and behavior when GitHub access is
unavailable. Keep issue creation, comments, branch creation, commits, pull
requests, merges, and other writes outside this capability.

## Type

`wayfinder:grilling` (human decision)

## Status

Resolved for MVP
