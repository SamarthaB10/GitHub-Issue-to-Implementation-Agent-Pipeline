from pathlib import Path

from agents.skill_catalog import SkillCatalog
from schemas.runtime import WorkerAssignment

PROJECT_ROOT = Path(__file__).parents[2]


def test_skill_catalog_exposes_core_building_skills(tmp_path):
    catalog = SkillCatalog.from_project(PROJECT_ROOT)

    skills = catalog.skills_for("runtime_worker")

    skill_names = [skill.name for skill in skills]
    assert "implement" in skill_names
    assert "tdd" in skill_names
    assert "triage" in skill_names
    assert "review-agent" in skill_names
    assert "code-review" in skill_names
    assert all(skill.skill_file.is_file() for skill in skills)
    assert all(skill.snapshot_dir.is_dir() for skill in skills)


def test_skill_catalog_declares_the_worker_pipeline_and_chief_ticket_skill():
    catalog = SkillCatalog.from_project(PROJECT_ROOT)

    assert catalog.required_skills_for("runtime_worker") == [
        "implement",
        "tdd",
        "code-review",
    ]
    assert "to-tickets" in catalog.required_skills_for("chief")


def test_skill_catalog_rejects_unknown_agent_role(tmp_path):
    catalog = SkillCatalog.from_project(PROJECT_ROOT)

    try:
        catalog.skills_for("unknown")
    except ValueError as exc:
        assert "Unknown agent role" in str(exc)
    else:
        raise AssertionError("Unknown agent role should be rejected")


def test_skill_catalog_prepares_context_for_every_subagent(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-copy-this-value")
    catalog = SkillCatalog.from_project(PROJECT_ROOT)
    assignment = WorkerAssignment(
        run_id="run-1",
        worker_id="worker-1",
        task_id="task-1",
        project_workspace=str(tmp_path / "project"),
        worktree_path=str(tmp_path / "worktree"),
        branch="chief/run-1/worker-1",
        base_commit="abc1234",
        assigned_paths=["src/**", "tests/**"],
        approved_checks=[["python", "-m", "pytest", "tests/unit"]],
    )

    context_dir = tmp_path / "worker-context"
    bundle = catalog.prepare_subagent_context(assignment, context_dir)

    assert bundle.rules_file == context_dir / "sub_agents.md"
    assert bundle.context_file == context_dir / "context.agent"
    rules = bundle.rules_file.read_text(encoding="utf-8")
    context = bundle.context_file.read_text(encoding="utf-8")
    assert "worker-1" in rules
    assert "src/**" in rules
    assert "implement" in context
    assert "docs/skills/snapshots/implement/SKILL.md" in context
    assert "docs/skills/snapshots/review-agent/SKILL.md" in context
    assert "Required Runtime worker pipeline" in context
    assert "do-not-copy-this-value" not in rules
    assert "do-not-copy-this-value" not in context
