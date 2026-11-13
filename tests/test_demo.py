from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.container import build_services
from app.core.config import Settings
from app.demo import DEMO_USERS, seed_demo


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    return seed_demo(tmp_path_factory.mktemp("demo") / "data")


def test_seed_creates_one_contract_per_state(demo) -> None:  # type: ignore[no-untyped-def]
    statuses = [c.status for c in demo.contracts]
    assert len(demo.contracts) == 9
    assert {
        "INITIAL", "COLLECTING_DATA", "CONFLICT_DETECTED",
        "PENDING_HUMAN_REVIEW", "APPROVED", "REJECTED",
    } <= set(statuses)  # fmt: skip
    assert statuses.count("COLLECTING_DATA") == 4 and [c.owner for c in demo.contracts].count("carlos") == 1


def test_seed_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    target = tmp_path / "data"
    first = seed_demo(target)
    with pytest.raises(FileExistsError):
        seed_demo(target)
    again = seed_demo(target, force=True)
    assert len(again.contracts) == 9 and {c.id for c in again.contracts}.isdisjoint(c.id for c in first.contracts)


def test_demo_env_file_boots_a_working_api(demo) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=demo.env_file)
    assert {u.name: u.role for u in settings.api_users} == {n: r for n, (r, _) in DEMO_USERS.items()}
    client = TestClient(create_app(build_services(settings, with_rag=False)))

    def visible(name: str) -> int:
        response = client.get("/contracts", headers={"X-API-Key": DEMO_USERS[name][1]})
        assert response.status_code == 200
        return len(response.json())

    assert (visible("ana"), visible("carlos"), visible("bruno")) == (8, 1, 3)  # lo que dice la guía


def test_demo_chat_and_attachment_are_available(demo) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=demo.env_file)
    client = TestClient(create_app(build_services(settings, with_rag=False)))
    headers = {"X-API-Key": DEMO_USERS["ana"][1]}
    conflict = next(c for c in demo.contracts if c.status == "CONFLICT_DETECTED")
    page = client.get(f"/contracts/{conflict.id}/messages", headers=headers).json()
    attachment = page["items"][0]["attachments"][0]
    assert attachment["filename"] == "dni.png"
    image = client.get(attachment["url"], headers=headers)
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"

    returned = [c for c in demo.contracts if "Devuelto" in c.description][0]
    system = [
        m["text"]
        for m in client.get(f"/contracts/{returned.id}/messages", headers=headers).json()["items"]
        if m["role"] == "system"
    ]
    assert any("Falta aclarar el lugar de trabajo" in text for text in system)


def test_openapi_snapshot_is_up_to_date() -> None:
    import json

    from app.api.main import app

    snapshot = Path("docs/openapi.json")
    assert snapshot.is_file(), "ejecutá: uv run python -m app.cli openapi"
    assert json.loads(snapshot.read_text(encoding="utf-8")) == app.openapi(), (
        "docs/openapi.json está desactualizado: ejecutá uv run python -m app.cli openapi"
    )
