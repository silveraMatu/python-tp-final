from __future__ import annotations

import os
import stat
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import ContractNotFoundError, UnsupportedDocumentError
from app.repositories.chat import ChatRole, DocumentRef
from app.repositories.sqlite_chat import SqliteChatRepository
from app.services.attachment_store import AttachmentStore, Upload, safe_display_name
from app.services.chat_service import ChatService


@pytest.fixture
def chat(tmp_path: Path) -> ChatService:
    return ChatService(SqliteChatRepository(tmp_path / "db.sqlite"), AttachmentStore(tmp_path / "att"))


def exchange(chat: ChatService, contract_id: UUID, n: int, uploads: list[Upload] | None = None):  # type: ignore[no-untyped-def]
    return chat.record_exchange(
        contract_id, "ana", f"mensaje {n}", uploads or [], f"respuesta {n}", "PROVIDE_DATA", "llm"
    )


def test_exchange_is_stored_in_order_with_roles(chat: ChatService) -> None:
    contract_id = uuid4()
    user, agent = chat.record_exchange(
        contract_id, "ana", "DNI 30123456", [], "Registré 1 dato", "PROVIDE_DATA", "llm",
        sources=["clausula:SEXTA"],
        documents=[DocumentRef(kind="draft", format="pdf", url="/x")],
    )  # fmt: skip
    chat.record_event(contract_id, "bruno", "El revisor bruno aprobó el contrato.")

    page = chat.history(contract_id)
    assert [m.seq for m in page.items] == [1, 2, 3]
    assert [m.role for m in page.items] == [ChatRole.USER, ChatRole.AGENT, ChatRole.SYSTEM]
    assert page.items[0].actor == "ana" and page.items[1].actor == "assistant"
    assert page.items[1].intent == "PROVIDE_DATA" and page.items[1].sources == ["clausula:SEXTA"]
    assert page.items[1].documents[0].url == "/x"
    assert page.items[2].actor == "bruno"
    assert (user.id, agent.id) == (page.items[0].id, page.items[1].id)
    assert page.items[0].timestamp.tzinfo is not None and not page.has_more


def test_pagination_walks_backwards(chat: ChatService) -> None:
    contract_id = uuid4()
    for n in range(1, 6):  # 10 mensajes
        exchange(chat, contract_id, n)

    newest = chat.history(contract_id, limit=4)
    assert [m.seq for m in newest.items] == [7, 8, 9, 10]
    assert newest.has_more and newest.next_before == 7
    older = chat.history(contract_id, limit=4, before=newest.next_before)
    assert [m.seq for m in older.items] == [3, 4, 5, 6] and older.next_before == 3
    oldest = chat.history(contract_id, limit=4, before=older.next_before)
    assert [m.seq for m in oldest.items] == [1, 2] and not oldest.has_more and oldest.next_before is None
    assert chat.history(contract_id, limit=10_000).items[-1].seq == 10  # el tope no rompe


def test_histories_are_isolated_per_contract(chat: ChatService) -> None:
    first, second = uuid4(), uuid4()
    exchange(chat, first, 1)
    exchange(chat, second, 1)
    exchange(chat, second, 2)
    assert [m.seq for m in chat.history(first).items] == [1, 2]
    assert [m.seq for m in chat.history(second).items] == [1, 2, 3, 4]
    assert chat.history(uuid4()).items == []


def test_attachments_are_saved_privately_and_served(chat: ChatService, tmp_path: Path) -> None:
    contract_id = uuid4()
    user, _ = exchange(chat, contract_id, 1, [Upload("dni.png", b"\x89PNG-datos"), Upload("form.pdf", b"%PDF-1.4")])

    assert [(a.filename, a.media_type, a.size_bytes) for a in user.attachments] == [
        ("dni.png", "image/png", 10),
        ("form.pdf", "application/pdf", 8),
    ]
    assert user.attachments[0].url == f"/contracts/{contract_id}/attachments/{user.attachments[0].id}"
    meta, path = chat.attachment_file(contract_id, user.attachments[0].id)
    assert path.read_bytes() == b"\x89PNG-datos" and meta.sha256 == user.attachments[0].sha256
    assert path.name != "dni.png" and path.parent.parent == (tmp_path / "att").resolve()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert chat.history(contract_id).items[0].attachments[1].filename == "form.pdf"


def test_attachment_of_another_contract_is_not_found(chat: ChatService) -> None:
    contract_id = uuid4()
    user, _ = exchange(chat, contract_id, 1, [Upload("dni.png", b"x")])
    with pytest.raises(ContractNotFoundError):
        chat.attachment_file(uuid4(), user.attachments[0].id)
    with pytest.raises(ContractNotFoundError):
        chat.attachment_file(contract_id, uuid4())


def test_failed_exchange_leaves_no_orphan_files(chat: ChatService, tmp_path: Path) -> None:
    contract_id = uuid4()
    with pytest.raises(UnsupportedDocumentError):
        exchange(chat, contract_id, 1, [Upload("ok.png", b"x"), Upload("malo.exe", b"x")])
    assert chat.history(contract_id).items == []
    assert [p for p in (tmp_path / "att").rglob("*") if p.is_file()] == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\dni.png", "dni.png"),
        ("<img src=x onerror=alert(1)>.png", "_img src_x onerror_alert(1)_.png"),
        ("dni\u202etxt.png", "dnitxt.png"),
        ("", "archivo"),
        ("ab" * 150 + ".png", "ab" * 60),
        ("a" * 300 + ".png", "aaaaa.png"),  # las repeticiones absurdas se colapsan
    ],
)
def test_display_names_are_sanitized(raw: str, expected: str) -> None:
    assert safe_display_name(raw) == expected


def test_path_traversal_through_stored_name_is_blocked(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "att")
    with pytest.raises(UnsupportedDocumentError):
        store.path_of(uuid4(), "../../../etc/passwd")
    saved = store.save(uuid4(), Upload("../../evil.png", b"x"))
    assert "/" not in saved.stored_name and saved.filename == "evil.png"


def test_history_survives_a_restart(tmp_path: Path) -> None:
    contract_id = uuid4()
    first = ChatService(SqliteChatRepository(tmp_path / "db.sqlite"), AttachmentStore(tmp_path / "att"))
    exchange(first, contract_id, 1, [Upload("dni.png", b"x")])
    second = ChatService(SqliteChatRepository(tmp_path / "db.sqlite"), AttachmentStore(tmp_path / "att"))
    page = second.history(contract_id)
    assert [m.text for m in page.items] == ["mensaje 1", "respuesta 1"]
    assert second.attachment_file(contract_id, page.items[0].attachments[0].id)[1].is_file()
