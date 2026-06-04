"""
Gestión de memoria persistente para Zenix 3.0.
Incluye base de datos SQLite para conversaciones, preferencias y proyectos.
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from config import Config

log = logging.getLogger("zenix.memory")

CONVERSATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    agent TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

PREFERENCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

PROJECTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    summary TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class MemoryManager:
    """Administra las bases de datos SQLite de memoria persistente."""

    def __init__(self):
        self.base_dir = Path(Config.MEMORY_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.conversation_db = self.base_dir / "conversation_memory.db"
        self.preferences_db = self.base_dir / "user_preferences.db"
        self.projects_db = self.base_dir / "project_memory.db"

        self._ensure_database(self.conversation_db, CONVERSATION_SCHEMA)
        self._ensure_database(self.preferences_db, PREFERENCES_SCHEMA)
        self._ensure_database(self.projects_db, PROJECTS_SCHEMA)

    def _ensure_database(self, db_path: Path, schema: str) -> None:
        try:
            with sqlite3.connect(str(db_path), timeout=10) as connection:
                connection.execute("PRAGMA journal_mode=WAL;")
                connection.executescript(schema)
                connection.commit()
        except Exception as exc:
            log.error("[MEMORY] No se pudo inicializar %s: %s", db_path, exc, exc_info=True)

    def _execute(self, db_path: Path, query: str, params: tuple | list | None = None) -> sqlite3.Cursor | None:
        try:
            connection = sqlite3.connect(str(db_path), timeout=10)
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            cursor.execute(query, params or ())
            connection.commit()
            return cursor
        except Exception as exc:
            log.error("[MEMORY] Error ejecutando consulta en %s: %s", db_path, exc, exc_info=True)
            return None

    def log_interaction(self, role: str, content: str, agent: str, model: str) -> None:
        self._execute(
            self.conversation_db,
            "INSERT INTO interactions (role, content, agent, model) VALUES (?, ?, ?, ?)",
            (role, content, agent, model),
        )

    def get_recent_interactions(self, limit: int = 10) -> list[dict[str, Any]]:
        cursor = self._execute(
            self.conversation_db,
            "SELECT role, content, agent, model, created_at FROM interactions ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        if cursor is None:
            return []
        rows = cursor.fetchall()
        cursor.connection.close()
        return [dict(row) for row in rows]

    def get_interaction_count(self) -> int:
        cursor = self._execute(
            self.conversation_db,
            "SELECT COUNT(1) AS total FROM interactions",
        )
        if cursor is None:
            return 0
        row = cursor.fetchone()
        cursor.connection.close()
        return int(row[0]) if row else 0

    def get_context_summary(self) -> str:
        total = self.get_interaction_count()
        if total == 0:
            return "No hay memoria de conversación cargada."

        recent = self.get_recent_interactions(limit=3)
        snippets = [entry["content"].replace("\n", " ")[:90] for entry in recent]
        return (
            f"Memoria cargada: {total} interacciones. Últimas: {' | '.join(snippets)}"
        )

    def get_preference(self, key: str, default: Any = None) -> Any:
        cursor = self._execute(
            self.preferences_db,
            "SELECT value FROM preferences WHERE key = ?",
            (key,),
        )
        if cursor is None:
            return default
        row = cursor.fetchone()
        cursor.connection.close()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except Exception:
            return row[0]

    def set_preference(self, key: str, value: Any) -> None:
        serialized = json.dumps(value, ensure_ascii=False)
        self._execute(
            self.preferences_db,
            "INSERT INTO preferences (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (key, serialized),
        )

    def save_project(self, name: str, summary: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        serialized = json.dumps(metadata or {}, ensure_ascii=False)
        self._execute(
            self.projects_db,
            "INSERT INTO projects (name, summary, metadata) VALUES (?, ?, ?)",
            (name, summary or "", serialized),
        )

    def get_recent_projects(self, limit: int = 5) -> list[dict[str, Any]]:
        cursor = self._execute(
            self.projects_db,
            "SELECT id, name, summary, metadata, created_at FROM projects ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        if cursor is None:
            return []
        rows = cursor.fetchall()
        cursor.connection.close()
        projects: list[dict[str, Any]] = []
        for row in rows:
            project = dict(row)
            try:
                project["metadata"] = json.loads(project.get("metadata", "{}"))
            except Exception:
                project["metadata"] = {}
            projects.append(project)
        return projects
