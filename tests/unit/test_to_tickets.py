from agents.to_tickets import tasks_from_handoff
from tests.unit.test_handoff import make_handoff


def test_to_tickets_preserves_order_and_adds_dependencies():
    handoff = make_handoff()
    handoff.implementation_plan.steps.append(
        handoff.implementation_plan.steps[0].model_copy(
            update={
                "order": 2,
                "description": "Add the regression test.",
                "affected_files": ["tests/test_auth.py"],
                "depends_on": [1],
            }
        )
    )

    tasks = tasks_from_handoff(handoff)

    assert [task.task_id for task in tasks] == ["run-1/step-1", "run-1/step-2"]
    assert tasks[0].blocked_by == []
    assert tasks[1].blocked_by == ["run-1/step-1"]
