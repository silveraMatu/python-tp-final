"""Adaptador SQLite del historial de conversación."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID, uuid4

from app.repositories.chat import (
    AttachmentMeta,
    ChatMessage,
    ChatPage,
    ChatRole,
    DocumentRef,
    NewMessage,
    StoredAttachment,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id                    TEXT PRIMARY KEY,
    contract_id           TEXT NOT NULL,
    seq                   INTEGER NOT NULL,
    timestamp             TEXT NOT NULL,
    role                  TEXT NOT NULL,
    actor                 TEXT NOT NULL,
    text                  TEXT NOT NULL,
    intent                TEXT,
    classification_source TEXT,
    meta                  TEXT NOT NULL DEFAULT '{}',
    UNIQUE (contract_id, seq)
);
CREATE TABLE IF NOT EXISTS chat_attachments (
    id          TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL,
    message_id  TEXT NOT NULL REFERENCES chat_messages(id),
    filename    TEXT NOT NULL,
    media_type  TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    stored_name TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_contract_seq ON chat_messages(contract_id, seq);
CREATE INDEX IF NOT EXISTS idx_chat_att_message ON chat_attachments(message_id);
"""


def _attachment_url(contract_id: UUID, attachment_id: UUID) -> str:
    return f"/contracts/{contract_id}/attachments/{attachment_id}"


class SqliteChatRepository:
    """Historial en la misma base SQLite que los contratos (una conexión por operación)."""

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

    # ------------------------------------------------------------------ #

    def append(self, contract_id: UUID, messages: Sequence[NewMessage]) -> List[ChatMessage]:
        if not messages:
            return []
        stored: List[ChatMessage] = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")  # serializa la asignación de seq entre procesos
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS last FROM chat_messages WHERE contract_id = ?",
                (str(contract_id),),
            ).fetchone()
            seq = int(row["last"])
            for message in messages:
                seq += 1
                message_id = uuid4()
                timestamp = datetime.now(timezone.utc)
                meta = {
                    "sources": list(message.sources),
                    "documents": [doc.model_dump() for doc in message.documents],
                }
                conn.execute(
                    "INSERT INTO chat_messages (id, contract_id, seq, timestamp, role, actor, text,"
                    " intent, classification_source, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(message_id), str(contract_id), seq, timestamp.isoformat(),
                        message.role.value, message.actor, message.text, message.intent,
                        message.classification_source, json.dumps(meta, ensure_ascii=False),
                    ),
                )  # fmt: skip
                attachments: List[AttachmentMeta] = []
                for item in message.attachments:
                    attachment_id = uuid4()
                    conn.execute(
                        "INSERT INTO chat_attachments (id, contract_id, message_id, filename,"
                        " media_type, size_bytes, sha256, stored_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(attachment_id), str(contract_id), str(message_id), item.filename,
                            item.media_type, item.size_bytes, item.sha256, item.stored_name,
                        ),
                    )  # fmt: skip
                    attachments.append(
                        AttachmentMeta(
                            id=attachment_id,
                            filename=item.filename,
                            media_type=item.media_type,
                            size_bytes=item.size_bytes,
                            sha256=item.sha256,
                            url=_attachment_url(contract_id, attachment_id),
                        )
                    )
                stored.append(
                    ChatMessage(
                        id=message_id,
                        seq=seq,
                        timestamp=timestamp,
                        role=message.role,
                        actor=message.actor,
                        text=message.text,
                        intent=message.intent,
                        classification_source=message.classification_source,
                        sources=list(message.sources),
                        documents=list(message.documents),
                        attachments=attachments,
                    )
                )
        return stored

    def page(self, contract_id: UUID, limit: int, before: Optional[int] = None) -> ChatPage:
        query = "SELECT * FROM chat_messages WHERE contract_id = ?"
        params: List[Any] = [str(contract_id)]
        if before is not None:
            query += " AND seq < ?"
            params.append(before)
        query += " ORDER BY seq DESC LIMIT ?"
        params.append(limit + 1)  # una de más para saber si hay anteriores

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            has_more = len(rows) > limit
            rows = rows[:limit][::-1]  # de más antiguo a más nuevo
            attachments = self._attachments_by_message(conn, [row["id"] for row in rows])

        items = [self._to_message(row, attachments.get(row["id"], [])) for row in rows]
        return ChatPage(
            items=items,
            has_more=has_more,
            next_before=items[0].seq if has_more and items else None,
        )

    def get_attachment(self, contract_id: UUID, attachment_id: UUID) -> Optional[StoredAttachment]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_attachments WHERE id = ? AND contract_id = ?",
                (str(attachment_id), str(contract_id)),
            ).fetchone()
        if row is None:
            return None
        return StoredAttachment(self._attachment_meta(row), row["stored_name"])

    # ------------------------------------------------------------------ #

    @staticmethod
    def _attachment_meta(row: sqlite3.Row) -> AttachmentMeta:
        return AttachmentMeta(
            id=UUID(row["id"]),
            filename=row["filename"],
            media_type=row["media_type"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            url=_attachment_url(UUID(row["contract_id"]), UUID(row["id"])),
        )

    def _attachments_by_message(
        self, conn: sqlite3.Connection, message_ids: Sequence[str]
    ) -> Dict[str, List[AttachmentMeta]]:
        grouped: Dict[str, List[AttachmentMeta]] = {}
        if not message_ids:
            return grouped
        marks = ",".join("?" for _ in message_ids)
        rows = conn.execute(
            f"SELECT * FROM chat_attachments WHERE message_id IN ({marks}) ORDER BY rowid",
            list(message_ids),
        ).fetchall()
        for row in rows:
            grouped.setdefault(row["message_id"], []).append(self._attachment_meta(row))
        return grouped

    @staticmethod
    def _to_message(row: sqlite3.Row, attachments: List[AttachmentMeta]) -> ChatMessage:
        meta = json.loads(row["meta"])
        return ChatMessage(
            id=UUID(row["id"]),
            seq=row["seq"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            role=ChatRole(row["role"]),
            actor=row["actor"],
            text=row["text"],
            intent=row["intent"],
            classification_source=row["classification_source"],
            sources=list(meta.get("sources", [])),
            documents=[DocumentRef.model_validate(d) for d in meta.get("documents", [])],
            attachments=attachments,
        )
