"""Adaptador SQLite de :class:`ContractRepository`."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from app.core.exceptions import ContractAlreadyExistsError, ContractNotFoundError
from app.repositories.base import AuditEntry
from app.schemas.contract import ContractData, ContractStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contracts (
    id         TEXT PRIMARY KEY,
    status     TEXT NOT NULL,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id TEXT NOT NULL REFERENCES contracts(id),
    timestamp   TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_contracts_status ON contracts(status);
CREATE INDEX IF NOT EXISTS idx_audit_contract ON audit_log(contract_id, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteContractRepository:
    """Guarda cada contrato como JSON y su historial en una tabla de auditoría.

    Abre una conexión por operación, por lo que es seguro usarlo desde varios hilos
    (requiere un archivo: ``:memory:`` no es compatible con ese esquema).
    """

    def __init__(self, database_path: str | Path) -> None:
        path = Path(database_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(path)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _audit(
        conn: sqlite3.Connection,
        contract: ContractData,
        actor: str,
        action: str,
        detail: Optional[str],
        timestamp: str,
    ) -> None:
        conn.execute(
            "INSERT INTO audit_log (contract_id, timestamp, actor, action, status, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(contract.id), timestamp, actor, action, contract.status.value, detail),
        )

    def create(self, contract: ContractData, actor: str) -> None:
        now = _now()
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO contracts (id, status, data, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(contract.id), contract.status.value, contract.model_dump_json(), now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ContractAlreadyExistsError(str(contract.id)) from exc
            self._audit(conn, contract, actor, "created", None, now)

    def get(self, contract_id: UUID) -> ContractData:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM contracts WHERE id = ?", (str(contract_id),)
            ).fetchone()
        if row is None:
            raise ContractNotFoundError(str(contract_id))
        return ContractData.model_validate_json(row["data"])

    def save(
        self,
        contract: ContractData,
        actor: str,
        action: str,
        detail: Optional[str] = None,
    ) -> None:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE contracts SET status = ?, data = ?, updated_at = ? WHERE id = ?",
                (contract.status.value, contract.model_dump_json(), now, str(contract.id)),
            )
            if cursor.rowcount == 0:
                raise ContractNotFoundError(str(contract.id))
            self._audit(conn, contract, actor, action, detail, now)

    def list(self, status: Optional[ContractStatus] = None) -> List[ContractData]:
        query = "SELECT data FROM contracts"
        params: tuple[str, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status.value,)
        query += " ORDER BY created_at, rowid"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [ContractData.model_validate_json(row["data"]) for row in rows]

    def history(self, contract_id: UUID) -> List[AuditEntry]:
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM contracts WHERE id = ?", (str(contract_id),)
            ).fetchone()
            if exists is None:
                raise ContractNotFoundError(str(contract_id))
            rows = conn.execute(
                "SELECT id, contract_id, timestamp, actor, action, status, detail "
                "FROM audit_log WHERE contract_id = ? ORDER BY id",
                (str(contract_id),),
            ).fetchall()
        return [AuditEntry.model_validate(dict(row)) for row in rows]
