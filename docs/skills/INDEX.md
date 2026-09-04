# Project skill catalog

This catalog is the reviewed source for skills that Chief can expose to a
Chief-created sub-agent. Each skill is stored as a complete portable snapshot
under `snapshots/`. The source path and snapshot policy are in `catalog.json`.

## Agent routes

Every sub-agent can access the available building skills in this catalog.

Runtime workers must follow this process for every implementation ticket:

`implement → tdd → code-review`

Runtime workers also receive `review-agent` and conditional skills. Chief checks
the Skill trace before it accepts a WorkerResult.

Chief uses `to-tickets` to turn an approved plan into dependency-aware
WorkerTask queue entries. Chief can use `triage`, `grilling`,
`domain-modeling`, and other available skills when the human invokes them.

## Skill snapshots

| Skill | Required route | Snapshot |
| --- | --- | --- |
| `implement` | Runtime worker | [`snapshots/implement/SKILL.md`](./snapshots/implement/SKILL.md) |
| `tdd` | Runtime worker | [`snapshots/tdd/SKILL.md`](./snapshots/tdd/SKILL.md) |
| `code-review` | Runtime worker | [`snapshots/code-review/SKILL.md`](./snapshots/code-review/SKILL.md) |
| `review-agent` | Available to Chief and workers | [`snapshots/review-agent/SKILL.md`](./snapshots/review-agent/SKILL.md) |
| `to-tickets` | Chief | [`snapshots/to-tickets/SKILL.md`](./snapshots/to-tickets/SKILL.md) |
| `triage` | Available to Chief and workers | [`snapshots/triage/SKILL.md`](./snapshots/triage/SKILL.md) |
| `grilling` | Available to Chief and workers | [`snapshots/grilling/SKILL.md`](./snapshots/grilling/SKILL.md) |
| `domain-modeling` | Available to Chief and workers | [`snapshots/domain-modeling/SKILL.md`](./snapshots/domain-modeling/SKILL.md) |
| `writing-for-agents` | Available to Chief and workers | [`snapshots/writing-for-agents/SKILL.md`](./snapshots/writing-for-agents/SKILL.md) |
| `diagnosing-bugs` | Conditional | [`snapshots/diagnosing-bugs/SKILL.md`](./snapshots/diagnosing-bugs/SKILL.md) |
| `resolving-merge-conflicts` | Conditional | [`snapshots/resolving-merge-conflicts/SKILL.md`](./snapshots/resolving-merge-conflicts/SKILL.md) |
| `frontend-ui-engineering` | Conditional | [`snapshots/frontend-ui-engineering/SKILL.md`](./snapshots/frontend-ui-engineering/SKILL.md) |
| `git-guardrails-claude-code` | Conditional | [`snapshots/git-guardrails-claude-code/SKILL.md`](./snapshots/git-guardrails-claude-code/SKILL.md) |

Snapshots are reviewed copies. Refresh them only after an explicit user
request. Never store API keys, access tokens, or other secrets in this catalog
or in a snapshot.
