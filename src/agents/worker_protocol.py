from dataclasses import dataclass

from schemas.runtime import WorkerResult

REQUIRED_WORKER_PIPELINE = (
    ("implement", "started"),
    ("tdd", "red"),
    ("tdd", "green"),
    ("code-review", "reviewed"),
)


@dataclass(frozen=True)
class SkillTraceDecision:
    """Chief's decision about whether a WorkerResult followed the process."""

    accepted: bool
    missing_phases: list[str]
    violations: list[str]


class SkillTraceGate:
    """Check the required Runtime worker process before result acceptance."""

    def check(self, result: WorkerResult) -> SkillTraceDecision:
        completed = {
            (trace.skill, trace.phase)
            for trace in result.skill_trace
            if trace.status == "completed"
        }
        missing = [
            f"{skill}:{phase}"
            for skill, phase in REQUIRED_WORKER_PIPELINE
            if (skill, phase) not in completed
        ]
        violations = []
        sequences = [trace.sequence for trace in result.skill_trace]
        if sequences != sorted(sequences):
            violations.append("Skill trace sequence is not ordered.")
        phase_sequences = {
            (trace.skill, trace.phase): trace.sequence
            for trace in result.skill_trace
            if trace.status == "completed"
        }
        ordered_sequences = [
            phase_sequences[(skill, phase)]
            for skill, phase in REQUIRED_WORKER_PIPELINE
            if (skill, phase) in phase_sequences
        ]
        if ordered_sequences != sorted(ordered_sequences):
            violations.append("Required Skill trace phases are out of order.")
        if result.status == "completed" and not result.commit:
            violations.append("A completed WorkerResult must include a commit.")

        return SkillTraceDecision(
            accepted=not missing and not violations,
            missing_phases=missing,
            violations=violations,
        )
