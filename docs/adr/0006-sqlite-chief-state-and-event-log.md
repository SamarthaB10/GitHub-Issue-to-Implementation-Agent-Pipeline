---
status: accepted
---

# SQLite Chief state and event log

Chief will use a project-local SQLite database as the authoritative durable
state store. It will keep immutable event records for state changes and
append-only structured JSONL logs for operational output. The database will use
forward-only transactional migrations, reject newer unknown schemas, and create
a backup before migration so interrupted sessions can resume safely.
