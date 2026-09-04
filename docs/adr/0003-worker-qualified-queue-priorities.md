---
status: accepted
---

# Worker-qualified queue IDs and priorities

Every `sub_agent_queue.md` entry will use an ID that includes its worker
identity and is unique across all workers in the run. Queue entries will use
exactly one of three priority values: `workflow` for regular work,
`error_detection` for bug detection or correction, and `immediate` for tasks of
extreme importance. Chief uses these values to route and order work while
preserving each worker's separate queue.
