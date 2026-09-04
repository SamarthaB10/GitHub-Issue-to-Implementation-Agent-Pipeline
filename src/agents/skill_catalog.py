import json
from dataclasses import dataclass
from pathlib import Path

from schemas.runtime import WorkerAssignment


@dataclass(frozen=True)
class SkillDescriptor:
    """One reviewed, portable skill snapshot."""

    name: str
    description: str
    source: str
    snapshot_dir: Path
    skill_file: Path


@dataclass(frozen=True)
class SubagentContextBundle:
    """The two files Chief gives to one Runtime sub-agent."""

    rules_file: Path
    context_file: Path


class SkillCatalog:
    """Load the project-local catalog of skills available to sub-agents."""

    def __init__(self, project_root: Path, entries: list[dict]):
        self.project_root = project_root
        self.entries = entries

    @classmethod
    def from_project(cls, project_root: Path | str) -> "SkillCatalog":
        root = Path(project_root).expanduser().resolve()
        manifest_path = root / "docs" / "skills" / "catalog.json"

        if not manifest_path.is_file():
            raise ValueError(f"Skill catalog is missing: {manifest_path}")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Skill catalog cannot be read: {exc}") from exc

        entries = manifest.get("skills")
        if not isinstance(entries, list):
            raise TypeError("Skill catalog must contain a skills list.")

        return cls(root, entries)

    def skills_for(self, role: str) -> list[SkillDescriptor]:
        role_entries = [
            entry
            for entry in self.entries
            if role in entry.get("roles", [])
        ]

        if not role_entries:
            raise ValueError(f"Unknown agent role or empty skill route: {role}")

        descriptors = []
        for entry in role_entries:
            name = entry.get("name")
            snapshot = entry.get("snapshot")
            if not isinstance(name, str) or not isinstance(snapshot, str):
                raise TypeError("Every skill catalog entry needs a name and snapshot.")

            snapshot_dir = (self.project_root / "docs" / "skills" / snapshot).resolve()
            try:
                snapshot_dir.relative_to(self.project_root)
            except ValueError as exc:
                raise ValueError(f"Skill snapshot escapes the project: {name}") from exc

            skill_file = snapshot_dir / "SKILL.md"
            if not skill_file.is_file():
                raise ValueError(f"Skill snapshot is incomplete: {skill_file}")

            descriptors.append(
                SkillDescriptor(
                    name=name,
                    description=str(entry.get("description", "")),
                    source=str(entry.get("source", "")),
                    snapshot_dir=snapshot_dir,
                    skill_file=skill_file,
                )
            )

        return descriptors

    def required_skills_for(self, role: str) -> list[str]:
        """Return the skills that the role must trace during its work."""

        if not any(role in entry.get("roles", []) for entry in self.entries):
            raise ValueError(f"Unknown agent role: {role}")
        return [
            entry["name"]
            for entry in self.entries
            if role in entry.get("roles", []) and role in entry.get("required_for", [])
        ]

    def prepare_subagent_context(
        self,
        assignment: WorkerAssignment,
        output_dir: Path | str,
        *,
        role: str = "runtime_worker",
    ) -> SubagentContextBundle:
        """Write the rules and context files before Chief opens a sub-agent."""

        output_path = Path(output_dir).expanduser().resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        skills = self.skills_for(role)
        required_skills = assignment.required_skills or self.required_skills_for(role)

        rules = f"""# Runtime sub-agent rules

You are Runtime worker `{assignment.worker_id}` for task `{assignment.task_id}`.
Run: `{assignment.run_id}`.

Read this file and `context.agent` before you start work.

## Work boundary

Work only in this assigned Worktree:

`{assignment.worktree_path}`

Your assigned scope is:

{chr(10).join(f"- `{path}`" for path in assignment.assigned_paths)}

Use the Runtime worker tools for file edits, approved checks, queue updates,
and Git actions. Keep all product changes inside the assigned scope. Report
progress and errors through your sub-agent queue.
Write the final WorkerResult JSON to:

`{assignment.worktree_path}/.chief-worker/result.json`

## Required work method

Read every skill listed in `context.agent`. Follow the Required Runtime worker
pipeline in that file. Emit a Skill trace for each pipeline phase. Complete the
required checks and review before reporting success. Report changed files,
commit ID, checks, Skill traces, errors, and open questions.

## Git boundary

Commit only on the assigned Worker branch. The user integrates selected
branches into Protected main. Do not integrate changes.
"""

        skill_lines = []
        for skill in skills:
            relative_skill = skill.skill_file.relative_to(self.project_root)
            skill_lines.append(
                f"- `{skill.name}`: `{relative_skill.as_posix()}`"
            )

        context = f"""# Runtime sub-agent context

role: {role}
run_id: {assignment.run_id}
worker_id: {assignment.worker_id}
task_id: {assignment.task_id}
worktree: {assignment.worktree_path}
worker_branch: {assignment.branch}
base_commit: {assignment.base_commit}
worker_queue: {assignment.worktree_path}/.chief-worker/sub_agent_queue.md
authoritative_queue: {assignment.project_workspace}/.chief/workers/{assignment.worker_id}/sub_agent_queue.md
result_path: {assignment.worktree_path}/.chief-worker/result.json
project_context: CONTEXT.md
skill_catalog: docs/skills/INDEX.md
required_skills: {", ".join(required_skills) or "None"}

## Required Runtime worker pipeline

{(" → ".join(required_skills) if required_skills else "No required skill pipeline")}

The worker must emit Skill traces for the required phases. Chief checks these
traces before it accepts a WorkerResult.

## Assigned paths

{chr(10).join(f"- `{path}`" for path in assignment.assigned_paths)}

## Approved checks

{chr(10).join(f"- `{json.dumps(check)}`" for check in assignment.approved_checks) or "- No checks are approved yet."}

## Available skill snapshots

{chr(10).join(skill_lines)}
"""

        rules_file = output_path / "sub_agents.md"
        context_file = output_path / "context.agent"
        rules_file.write_text(rules, encoding="utf-8")
        context_file.write_text(context, encoding="utf-8")

        return SubagentContextBundle(
            rules_file=rules_file,
            context_file=context_file,
        )
