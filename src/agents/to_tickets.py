"""Convert one approved Planner handoff into dependency-aware WorkerTasks."""

from schemas.runtime import PlannerHandoff, WorkerTask


def tasks_from_handoff(handoff: PlannerHandoff) -> list[WorkerTask]:
    """Create one ordered vertical-slice ticket for each plan step."""

    steps = sorted(handoff.implementation_plan.steps, key=lambda step: step.order)
    if [step.order for step in steps] != list(range(1, len(steps) + 1)):
        raise ValueError("Implementation plan steps must have contiguous order values.")

    tasks = []
    task_ids_by_order = {step.order: f"{handoff.run_id}/step-{step.order}" for step in steps}
    for step in steps:
        if any(dependency not in task_ids_by_order for dependency in step.depends_on):
            raise ValueError("Implementation step dependency does not exist.")
        task_id = task_ids_by_order[step.order]
        description = f"{step.description}\n\nRationale: {step.rationale}"
        if handoff.implementation_plan.planned_tests:
            test_lines = "\n".join(
                f"- {planned.description}"
                for planned in handoff.implementation_plan.planned_tests
            )
            description += f"\n\nPlanned verification:\n{test_lines}"
        tasks.append(
            WorkerTask(
                run_id=handoff.run_id,
                task_id=task_id,
                title=f"Step {step.order}: {step.description}",
                description=description,
                blocked_by=[task_ids_by_order[dependency] for dependency in step.depends_on],
                acceptance_criteria=handoff.issue_brief.acceptance_criteria,
                assigned_paths=step.affected_files or ["src/**"],
                required_checks=handoff.approved_checks,
            )
        )
    return tasks
