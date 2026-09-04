"""Local Chief command boundary for cloned project workspaces."""

import argparse
import json
from pathlib import Path

from agents.chief import ChiefCoordinator
from agents.lifecycle import WorkerLifecycleManager
from agents.providers import CommandProvider
from schemas.runtime import PlannerHandoff


def _handoff(path: str) -> PlannerHandoff:
    return PlannerHandoff.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _chief_for(handoff: PlannerHandoff) -> ChiefCoordinator:
    return ChiefCoordinator(handoff.repository_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chief", description="Supervise GH-Pipeline workers.")
    commands = parser.add_subparsers(dest="command", required=True)

    handoff = commands.add_parser("handoff", help="Accept an approved Planner handoff.")
    handoff.add_argument("--file", required=True)

    delegate = commands.add_parser("delegate", help="Create worker worktrees and queues.")
    delegate.add_argument("--file", required=True)
    delegate.add_argument("--provider", choices=("codex", "claude"), default="codex")

    run = commands.add_parser("run", help="Delegate and supervise workers in order.")
    run.add_argument("--file", required=True)
    run.add_argument("--provider", choices=("codex", "claude"), default="codex")

    for name in ("status", "report"):
        command = commands.add_parser(name)
        command.add_argument("--project", required=True)
        command.add_argument("--run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {"handoff", "delegate", "run"}:
        handoff = _handoff(args.file)
        chief = _chief_for(handoff)
        if args.command == "handoff":
            tasks = chief.create_tasks_from_handoff(handoff)
            print(json.dumps({"run_id": handoff.run_id, "task_ids": [task.task_id for task in tasks]}))
        else:
            assignments = chief.delegate_tasks(handoff, provider=args.provider)
            if args.command == "delegate":
                print(json.dumps({"run_id": handoff.run_id, "workers": [assignment.worker_id for assignment in assignments]}))
            else:
                lifecycle = WorkerLifecycleManager(chief)
                outcomes = []
                provider = CommandProvider.from_environment(args.provider)
                for assignment in assignments:
                    lifecycle.start(assignment, provider)
                    outcome = lifecycle.wait(assignment.worker_id)
                    outcomes.append({"worker_id": assignment.worker_id, "accepted": outcome.accepted})
                    if not outcome.accepted:
                        break
                print(json.dumps({"run_id": handoff.run_id, "outcomes": outcomes}))
        return 0

    chief = ChiefCoordinator(args.project)
    if args.command == "status":
        print(json.dumps({"run": chief.state_store.get_run(args.run_id), "events": chief.state_store.events_for_run(args.run_id)}))
    else:
        print(chief.integration_report(args.run_id).model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
