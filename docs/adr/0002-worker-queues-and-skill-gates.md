---
status: accepted
---

# Worker queues and skill gates

Each worker will have a dedicated `sub_agent_queue.md` containing tasks and
worker-specific change requests written by Chief. Workers pull only their own
queue entries and must follow a skill protocol during implementation: TDD for
behavior changes, the implementation lifecycle, UI engineering rules for UI
work, regular checks, and code review before reporting a result. This makes
Chief's supervision explicit and keeps implementation quality consistent across
parallel workers.
