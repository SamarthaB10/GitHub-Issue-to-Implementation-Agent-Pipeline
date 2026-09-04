import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from schemas.runtime import (
    PlannerHandoff,
    QueueEntry,
    WorkerAssignment,
    WorkerResult,
    WorkerTask,
)

LATEST_SCHEMA_VERSION = 2


class StateStoreError(RuntimeError):
    """Raised when Chief cannot safely open or update its state store."""


class ChiefStateStore:
    """Persist Chief supervision state in a project-local SQLite database."""

    def __init__(self, project_workspace: Path | str):
        self.project_workspace = Path(project_workspace).expanduser().resolve()
        self.db_path = self.project_workspace / ".chief" / "chief.sqlite3"

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        existing_database = self.db_path.is_file()
        connection = sqlite3.connect(self.db_path)
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > LATEST_SCHEMA_VERSION:
                raise StateStoreError(
                    "Chief state store has a newer schema than this runtime."
                )
            if version < LATEST_SCHEMA_VERSION and existing_database:
                backup_path = self.db_path.with_suffix(".sqlite3.bak")
                shutil.copy2(self.db_path, backup_path)
            self._create_schema(connection)
            connection.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION}")
            connection.commit()
        finally:
            connection.close()

    def create_run(
        self,
        run_id: str,
        *,
        base_commit: str,
        status: str = "created",
    ) -> None:
        now = self._now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO runs
                    (run_id, project_workspace, base_commit, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, str(self.project_workspace), base_commit, status, now, now),
            )
            self._insert_event(connection, run_id, "run_created", {"status": status})

    def set_run_status(self, run_id: str, status: str) -> None:
        now = self._now()
        with self._connection() as connection:
            self._require_run(connection, run_id)
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status, now, run_id),
            )
            self._insert_event(connection, run_id, "run_status_changed", {"status": status})

    def record_task(self, task: WorkerTask) -> None:
        with self._connection() as connection:
            self._require_run(connection, task.run_id)
            self._insert_payload(
                connection,
                "tasks",
                "task_id",
                task.task_id,
                task.run_id,
                task.model_dump(mode="json"),
            )
            self._insert_event(connection, task.run_id, "task_recorded", {"task_id": task.task_id})

    def record_handoff(self, handoff: PlannerHandoff) -> None:
        """Persist the validated Planner artifact bundle for a run."""

        with self._connection() as connection:
            self._require_run(connection, handoff.run_id)
            connection.execute(
                """
                INSERT INTO planner_handoffs (run_id, payload_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    handoff.run_id,
                    self._dump(handoff.model_dump(mode="json")),
                    self._now(),
                ),
            )
            self._insert_event(
                connection,
                handoff.run_id,
                "planner_handoff_recorded",
                {"schema_version": handoff.schema_version},
            )

    def record_worker(self, assignment: WorkerAssignment) -> None:
        with self._connection() as connection:
            self._require_run(connection, assignment.run_id)
            self._insert_payload(
                connection,
                "workers",
                "worker_id",
                assignment.worker_id,
                assignment.run_id,
                assignment.model_dump(mode="json"),
            )
            self._insert_event(
                connection,
                assignment.run_id,
                "worker_recorded",
                {"worker_id": assignment.worker_id},
            )

    def record_queue_entry(self, entry: QueueEntry) -> None:
        with self._connection() as connection:
            self._require_run(connection, entry.run_id)
            self._insert_payload(
                connection,
                "queue_entries",
                "queue_id",
                entry.queue_id,
                entry.run_id,
                entry.model_dump(mode="json"),
            )
            self._insert_event(
                connection,
                entry.run_id,
                "queue_entry_recorded",
                {"queue_id": entry.queue_id},
            )

    def record_worker_result(self, result: WorkerResult) -> None:
        with self._connection() as connection:
            self._require_run(connection, result.run_id)
            connection.execute(
                """
                INSERT INTO worker_results
                    (run_id, worker_id, task_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, worker_id, task_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    result.run_id,
                    result.worker_id,
                    result.task_id,
                    self._dump(result.model_dump(mode="json")),
                    self._now(),
                ),
            )
            self._insert_event(
                connection,
                result.run_id,
                "worker_result_recorded",
                {"worker_id": result.worker_id, "task_id": result.task_id},
            )

    def record_event(self, run_id: str, event_type: str, payload: dict[str, object]) -> None:
        with self._connection() as connection:
            self._require_run(connection, run_id)
            self._insert_event(connection, run_id, event_type, payload)

    def get_run(self, run_id: str) -> dict[str, object] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT run_id, project_workspace, base_commit, status, created_at, updated_at
                FROM runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row[0],
            "project_workspace": row[1],
            "base_commit": row[2],
            "status": row[3],
            "created_at": row[4],
            "updated_at": row[5],
        }

    def get_task(self, task_id: str) -> dict[str, object] | None:
        return self._get_payload("tasks", "task_id", task_id)

    def get_handoff(self, run_id: str) -> dict[str, object] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM planner_handoffs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def get_worker(self, worker_id: str) -> dict[str, object] | None:
        return self._get_payload("workers", "worker_id", worker_id)

    def get_queue_entry(self, queue_id: str) -> dict[str, object] | None:
        return self._get_payload("queue_entries", "queue_id", queue_id)

    def tasks_for_run(self, run_id: str) -> list[dict[str, object]]:
        return self._payloads_for_run("tasks", run_id)

    def workers_for_run(self, run_id: str) -> list[dict[str, object]]:
        return self._payloads_for_run("workers", run_id)

    def worker_results_for_run(self, run_id: str) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM worker_results WHERE run_id = ? ORDER BY created_at",
                (run_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def events_for_run(self, run_id: str) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT event_id, run_id, event_type, payload_json, created_at
                FROM events WHERE run_id = ? ORDER BY event_id
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "event_id": row[0],
                "run_id": row[1],
                "event_type": row[2],
                "payload": json.loads(row[3]),
                "created_at": row[4],
            }
            for row in rows
        ]

    def _connection(self) -> sqlite3.Connection:
        self.initialize()
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                project_workspace TEXT NOT NULL,
                base_commit TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT NOT NULL,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                payload_json TEXT NOT NULL,
                PRIMARY KEY (run_id, task_id)
            );
            CREATE TABLE IF NOT EXISTS planner_handoffs (
                run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workers (
                worker_id TEXT NOT NULL,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                payload_json TEXT NOT NULL,
                PRIMARY KEY (run_id, worker_id)
            );
            CREATE TABLE IF NOT EXISTS queue_entries (
                queue_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS worker_results (
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                worker_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (run_id, worker_id, task_id)
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

    @staticmethod
    def _insert_payload(
        connection: sqlite3.Connection,
        table: str,
        key_name: str,
        key_value: str,
        run_id: str,
        payload: dict[str, object],
    ) -> None:
        connection.execute(
            f"""
            INSERT INTO {table} ({key_name}, run_id, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT DO UPDATE SET payload_json = excluded.payload_json
            """,
            (key_value, run_id, ChiefStateStore._dump(payload)),
        )

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        connection.execute(
            """
            INSERT INTO events (run_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, event_type, ChiefStateStore._dump(payload), ChiefStateStore._now()),
        )

    @staticmethod
    def _require_run(connection: sqlite3.Connection, run_id: str) -> None:
        row = connection.execute(
            "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise StateStoreError(f"Run does not exist: {run_id}")

    def _get_payload(
        self,
        table: str,
        key_name: str,
        key_value: str,
    ) -> dict[str, object] | None:
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {table} WHERE {key_name} = ?",
                (key_value,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def _payloads_for_run(self, table: str, run_id: str) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {table} WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    @staticmethod
    def _dump(payload: dict[str, object]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
