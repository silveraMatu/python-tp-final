from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
from uuid import UUID

import pymupdf
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.intents import IntentClassifier
from app.agent.service import AgentService
from app.api.auth import ApiKeyAuthenticator, Role, generate_api_key, hash_api_key
from app.api.main import create_app
from app.container import Services
from app.core.config import ApiUserConfig, Settings
from app.core.exceptions import LLMUnavailableError
from app.repositories.sqlite import SqliteContractRepository
from app.services.contract_service import ContractService
from app.services.document_loader import DocumentLoader
from app.services.export_service import ExportService
from app.services.extraction_service import ExtractionService
from app.services.template_service import ContractTemplateService
from app.services.validation_service import ValidationService
from tests.helpers import (
    FakePdfConverter,
    FakeRag,
    ScriptedLLM,
    extraction_json,
    intent_json,
)
from tests.test_contract_service import FULL_VALUES, batch
from tests.test_export_service import TEMPLATE

KEYS = {"ana": "key-ana", "carlos": "key-carlos", "bruno": "key-bruno"}
ROLES = {"ana": "REQUESTER", "carlos": "REQUESTER", "bruno": "REVIEWER"}


def auth(name: str) -> Dict[str, str]:
    return {"X-API-Key": KEYS[name]}


class DownLLM(ScriptedLLM):
    def generate_json(
        self, *, system: str, user: str, schema: Mapping[str, Any], images: Sequence[bytes] = ()
    ) -> str:
        raise LLMUnavailableError("sin créditos (402)")


@dataclass
class Api:
    client: TestClient
    services: Services
    llm: ScriptedLLM
    tmp: Path

    def create(self, name: str = "ana") -> str:
        response = self.client.post("/contracts", headers=auth(name))
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    def fill(self, contract_id: str) -> None:
        self.services.contracts.apply_extraction(UUID(contract_id), batch(FULL_VALUES), "ana")

    def submit(self, contract_id: str) -> None:
        assert self.client.post(f"/contracts/{contract_id}/submit", headers=auth("ana")).status_code == 200

    def approve(self, contract_id: str, comment: Optional[str] = None) -> None:
        body: Dict[str, Any] = {"decision": "APPROVE", "comment": comment}
        response = self.client.post(f"/contracts/{contract_id}/review", json=body, headers=auth("bruno"))
        assert response.status_code == 200, response.text


def build_api(tmp_path: Path, llm: Optional[ScriptedLLM] = None, with_rag: bool = True) -> Api:
    settings = Settings(
        api_users=[
            ApiUserConfig(name=name, role=ROLES[name], key_sha256=hash_api_key(KEYS[name]))  # type: ignore[arg-type]
            for name in KEYS
        ],
        database_path=tmp_path / "db.sqlite",
        output_dir=tmp_path / "out",
        template_path=Path(TEMPLATE),
        max_upload_bytes=20_000,
        max_upload_files=2,
        _env_file=None,
    )
    llm = llm or ScriptedLLM()
    templates = ContractTemplateService(today=lambda: date(2026, 11, 3))
    contracts = ContractService(
        SqliteContractRepository(settings.database_path),
        ValidationService(0.8),
        templates,
        settings.template_path,
    )
    exporter = ExportService(
        contracts, templates, FakePdfConverter(), settings.template_path, settings.output_dir
    )
    rag = FakeRag() if with_rag else None
    agent = AgentService(
        contracts,
        ExtractionService(llm, max_retries=0),
        IntentClassifier(llm),
        rag,  # type: ignore[arg-type]
        exporter,
    )
    services = Services(
        settings, contracts, templates, exporter, agent,
        DocumentLoader(max_bytes=settings.max_upload_bytes), rag,  # type: ignore[arg-type]
    )  # fmt: skip
    return Api(TestClient(create_app(services)), services, llm, tmp_path)


@pytest.fixture
def api(tmp_path: Path) -> Api:
    return build_api(tmp_path)


def png_bytes() -> bytes:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 48), False)
    pixmap.clear_with(255)
    return bytes(pixmap.tobytes("png"))


# --------------------------------------------------------------------------- #
# Autenticación y roles
# --------------------------------------------------------------------------- #


def test_health_is_public_and_the_rest_requires_a_key(api: Api) -> None:
    assert api.client.get("/health").json() == {"status": "ok"}
    for method, url in (("get", "/me"), ("get", "/contracts"), ("post", "/contracts")):
        response = getattr(api.client, method)(url)
        assert response.status_code == 401 and response.headers["www-authenticate"] == "ApiKey"
    assert api.client.get("/me", headers={"X-API-Key": "inventada"}).status_code == 401


def test_me_returns_name_and_role(api: Api) -> None:
    assert api.client.get("/me", headers=auth("bruno")).json() == {"name": "bruno", "role": "REVIEWER"}


def test_api_without_configured_users_rejects_everything(tmp_path: Path) -> None:
    open_api = build_api(tmp_path)
    open_api.client.app.state.authenticator = ApiKeyAuthenticator([])  # type: ignore[attr-defined]
    assert open_api.client.get("/me", headers=auth("ana")).status_code == 401


def test_api_keys_are_stored_hashed_and_generated_randomly() -> None:
    key, digest = generate_api_key()
    assert key.startswith("hk_") and digest == hash_api_key(key) and key not in digest
    assert generate_api_key()[0] != key
    authenticator = ApiKeyAuthenticator([ApiUserConfig(name="x", role="REVIEWER", key_sha256=digest)])
    user = authenticator.authenticate(key)
    assert user is not None and user.role is Role.REVIEWER
    assert authenticator.authenticate(key + "x") is None and authenticator.authenticate(None) is None
    with pytest.raises(ValidationError):
        ApiUserConfig(name="x", role="REVIEWER", key_sha256="no-es-un-hash")


def test_only_requesters_create_contracts(api: Api) -> None:
    assert api.client.post("/contracts", headers=auth("bruno")).status_code == 403
    response = api.client.post("/contracts", headers=auth("ana"))
    assert response.status_code == 201
    body = response.json()
    assert response.headers["location"] == f"/contracts/{body['id']}"
    assert body["status"] == "INITIAL" and body["created_by"] == "ana"
    assert "send_message" in body["allowed_actions"] and len(body["missing_fields"]) == 17


# --------------------------------------------------------------------------- #
# Visibilidad
# --------------------------------------------------------------------------- #


def test_requesters_only_see_their_own_contracts(api: Api) -> None:
    contract_id = api.create("ana")
    assert api.client.get(f"/contracts/{contract_id}", headers=auth("ana")).status_code == 200
    assert api.client.get(f"/contracts/{contract_id}", headers=auth("carlos")).status_code == 404
    assert api.client.get(f"/contracts/{contract_id}/history", headers=auth("carlos")).status_code == 404
    assert [c["id"] for c in api.client.get("/contracts", headers=auth("ana")).json()] == [contract_id]
    assert api.client.get("/contracts", headers=auth("carlos")).json() == []


def test_reviewers_only_see_contracts_that_reached_review(api: Api) -> None:
    contract_id = api.create("ana")
    api.fill(contract_id)
    assert api.client.get(f"/contracts/{contract_id}", headers=auth("bruno")).status_code == 404
    assert api.client.get("/contracts", headers=auth("bruno")).json() == []

    api.submit(contract_id)
    seen = api.client.get("/contracts", headers=auth("bruno")).json()
    assert [c["id"] for c in seen] == [contract_id]
    assert seen[0]["allowed_actions"] == ["get_draft", "review"]
    only_pending = api.client.get("/contracts?status_filter=APPROVED", headers=auth("bruno")).json()
    assert only_pending == []


def test_contracts_are_not_editable_by_other_users(api: Api) -> None:
    contract_id = api.create("ana")
    for url in ("messages", "submit", "conflicts/resolve"):
        kwargs: Dict[str, Any] = {"json": {"field_name": "employee.dni", "accept_new": True}} if "resolve" in url else {}
        assert api.client.post(f"/contracts/{contract_id}/{url}", headers=auth("carlos"), **kwargs).status_code == 404
    assert api.client.post(f"/contracts/{contract_id}/messages", headers=auth("bruno"), data={"message": "hola"}).status_code == 403


# --------------------------------------------------------------------------- #
# Conversación
# --------------------------------------------------------------------------- #


def test_message_runs_the_agent_and_returns_the_contract(api: Api) -> None:
    contract_id = api.create()
    api.llm.push("intent", intent_json("PROVIDE_DATA"))
    api.llm.push("extraction", extraction_json(("employee.dni", "30.123.456", "DNI 30.123.456", 0.97)))
    response = api.client.post(
        f"/contracts/{contract_id}/messages", headers=auth("ana"), data={"message": "DNI 30.123.456"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "PROVIDE_DATA" and "Registré 1 dato(s)" in body["reply"]
    assert body["contract"]["status"] == "COLLECTING_DATA"
    assert body["contract"]["fields"] == [
        {"field_name": "employee.dni", "label": "DNI del empleado/a", "value": "30.123.456"}
    ]
    assert body["documents"] == [] and "employee.dni" not in body["contract"]["missing_fields"]


def test_message_validation_and_upload_limits(api: Api) -> None:
    contract_id = api.create()
    url = f"/contracts/{contract_id}/messages"
    assert api.client.post(url, headers=auth("ana"), data={"message": "  "}).status_code == 422

    too_many = [("files", (f"f{i}.png", png_bytes(), "image/png")) for i in range(3)]
    assert api.client.post(url, headers=auth("ana"), files=too_many).status_code == 413

    huge = [("files", ("grande.png", b"0" * 20_001, "image/png"))]
    response = api.client.post(url, headers=auth("ana"), files=huge)
    assert response.status_code == 413 and "supera el máximo" in response.json()["detail"]

    bad_type = [("files", ("notas.txt", b"hola", "text/plain"))]
    response = api.client.post(url, headers=auth("ana"), files=bad_type)
    assert response.status_code == 422 and response.json()["error"] == "unsupported_document"
    assert api.llm.calls == []  # nada de esto llegó al modelo


def test_image_upload_is_extracted_and_never_stored_or_exposed(api: Api) -> None:
    contract_id = api.create()
    api.llm.push("extraction", extraction_json(("employee.dni", "30123456", "30.123.456", 0.98)))
    response = api.client.post(
        f"/contracts/{contract_id}/messages",
        headers=auth("ana"),
        files=[("files", ("dni.png", png_bytes(), "image/png"))],
    )
    assert response.status_code == 200
    assert response.json()["contract"]["fields"][0]["value"] == "30.123.456"
    assert str(api.tmp) not in response.text  # no se exponen rutas del servidor
    assert not list(api.tmp.rglob("dni.png"))  # y el adjunto no se guarda


def test_conflict_can_be_resolved_through_the_api(api: Api) -> None:
    contract_id = api.create()
    api.llm.push("intent", intent_json("PROVIDE_DATA"))
    api.llm.push("extraction", extraction_json(("employee.dni", "30123456", "DNI 30123456", 0.5)))
    body = api.client.post(
        f"/contracts/{contract_id}/messages", headers=auth("ana"), data={"message": "DNI 30123456"}
    ).json()
    assert body["contract"]["status"] == "CONFLICT_DETECTED"
    assert body["contract"]["pending_conflicts"][0]["field_name"] == "employee.dni"
    assert "resolve_conflict" in body["contract"]["allowed_actions"]

    resolve = {"field_name": "employee.dni", "accept_new": True}
    ok = api.client.post(f"/contracts/{contract_id}/conflicts/resolve", json=resolve, headers=auth("ana"))
    assert ok.status_code == 200 and ok.json()["status"] == "COLLECTING_DATA"
    again = api.client.post(f"/contracts/{contract_id}/conflicts/resolve", json=resolve, headers=auth("ana"))
    assert again.status_code == 409 and again.json()["error"] == "no_pending_conflict"


def test_llm_outage_is_a_503(tmp_path: Path) -> None:
    api = build_api(tmp_path, llm=DownLLM())
    contract_id = api.create()
    response = api.client.post(
        f"/contracts/{contract_id}/messages", headers=auth("ana"), data={"message": "El DNI es 30123456"}
    )
    assert response.status_code == 503 and response.json()["error"] == "llm_unavailable"


# --------------------------------------------------------------------------- #
# Envío y revisión humana
# --------------------------------------------------------------------------- #


def test_submit_requires_complete_data(api: Api) -> None:
    contract_id = api.create()
    response = api.client.post(f"/contracts/{contract_id}/submit", headers=auth("ana"))
    assert response.status_code == 409 and response.json()["error"] == "invalid_state_transition"
    api.fill(contract_id)
    response = api.client.post(f"/contracts/{contract_id}/submit", headers=auth("ana"))
    assert response.status_code == 200 and response.json()["status"] == "PENDING_HUMAN_REVIEW"
    assert api.client.post("/contracts", headers=auth("ana")).status_code == 201  # no afecta a otros


def test_only_a_reviewer_can_decide(api: Api) -> None:
    contract_id = api.create()
    api.fill(contract_id)
    api.submit(contract_id)
    body = {"decision": "APPROVE"}
    assert api.client.post(f"/contracts/{contract_id}/review", json=body, headers=auth("ana")).status_code == 403
    assert api.client.post(f"/contracts/{contract_id}/review", json=body, headers=auth("carlos")).status_code == 403
    assert api.client.get(f"/contracts/{contract_id}", headers=auth("ana")).json()["status"] == "PENDING_HUMAN_REVIEW"

    api.approve(contract_id, "Todo en orden")
    approved = api.client.get(f"/contracts/{contract_id}", headers=auth("ana")).json()
    assert approved["status"] == "APPROVED"
    history = api.client.get(f"/contracts/{contract_id}/history", headers=auth("ana")).json()
    decision = [h for h in history if h["action"] == "approved"][0]
    assert decision["actor"] == "bruno" and decision["detail"] == "Todo en orden"

    again = api.client.post(f"/contracts/{contract_id}/review", json=body, headers=auth("bruno"))
    assert again.status_code == 409


def test_reject_and_request_changes(api: Api) -> None:
    rejected = api.create()
    api.fill(rejected)
    api.submit(rejected)
    response = api.client.post(
        f"/contracts/{rejected}/review", json={"decision": "REJECT", "comment": "Falta firma"}, headers=auth("bruno")
    )
    assert response.json()["status"] == "REJECTED"

    returned = api.create()
    api.fill(returned)
    api.submit(returned)
    response = api.client.post(
        f"/contracts/{returned}/review", json={"decision": "REQUEST_CHANGES"}, headers=auth("bruno")
    )
    assert response.status_code == 200 and response.json()["status"] == "COLLECTING_DATA"
    assert api.client.get(f"/contracts/{returned}", headers=auth("ana")).json()["status"] == "COLLECTING_DATA"
    assert api.client.get(f"/contracts/{returned}", headers=auth("bruno")).status_code == 404


def test_review_payload_is_validated(api: Api) -> None:
    contract_id = api.create()
    api.fill(contract_id)
    api.submit(contract_id)
    url = f"/contracts/{contract_id}/review"
    assert api.client.post(url, json={"decision": "MAYBE"}, headers=auth("bruno")).status_code == 422
    assert api.client.post(url, json={"decision": "APPROVE", "x": 1}, headers=auth("bruno")).status_code == 422
    assert api.client.post(url, json={"decision": "APPROVE", "comment": "x" * 501}, headers=auth("bruno")).status_code == 422


# --------------------------------------------------------------------------- #
# Documentos
# --------------------------------------------------------------------------- #


def test_draft_download(api: Api) -> None:
    contract_id = api.create()
    url = f"/contracts/{contract_id}/document?version=draft"
    assert api.client.get(url, headers=auth("ana")).json()["error"] == "incomplete_contract"

    api.fill(contract_id)
    response = api.client.get(url, headers=auth("ana"))
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].endswith(f'borrador-{contract_id}.pdf"')
    assert len(response.headers["x-verification-code"]) == 14

    assert api.client.get(url + "&format=docx", headers=auth("ana")).status_code == 422
    assert api.client.get(url, headers=auth("carlos")).status_code == 404
    assert api.client.get(url, headers=auth("bruno")).status_code == 404  # aún no llegó a revisión

    api.submit(contract_id)
    assert api.client.get(url, headers=auth("bruno")).status_code == 200


def test_final_requires_approval_then_is_issued_once(api: Api) -> None:
    contract_id = api.create()
    api.fill(contract_id)
    final = f"/contracts/{contract_id}/document?version=final"
    assert api.client.get(final, headers=auth("ana")).status_code == 409
    api.submit(contract_id)
    assert api.client.get(final, headers=auth("bruno")).status_code == 409
    api.approve(contract_id)

    pdf = api.client.get(final + "&format=pdf", headers=auth("ana"))
    docx = api.client.get(final + "&format=docx", headers=auth("bruno"))
    assert pdf.status_code == docx.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert docx.headers["content-type"].endswith("wordprocessingml.document")
    assert docx.content.startswith(b"PK")
    again = api.client.get(final + "&format=pdf", headers=auth("ana"))
    assert again.content == pdf.content and again.headers["x-verification-code"] == pdf.headers["x-verification-code"]
    assert api.client.get(f"/contracts/{contract_id}/document?version=draft", headers=auth("ana")).status_code == 409

    actions = [h["action"] for h in api.client.get(f"/contracts/{contract_id}/history", headers=auth("ana")).json()]
    assert actions.count("exported_final") == 1


def test_verification_detects_a_tampered_final(api: Api) -> None:
    contract_id = api.create()
    api.fill(contract_id)
    api.submit(contract_id)
    api.approve(contract_id)
    final = f"/contracts/{contract_id}/document?version=final"
    assert api.client.get(final, headers=auth("ana")).status_code == 200
    verification = f"/contracts/{contract_id}/verification"
    assert api.client.get(verification, headers=auth("bruno")).json()["ok"] is True

    pdf = api.services.exporter._folder(UUID(contract_id)) / "contrato_final.pdf"  # type: ignore[attr-defined]
    pdf.write_bytes(pdf.read_bytes() + b"\n%alterado")
    report = api.client.get(verification, headers=auth("ana")).json()
    assert report["ok"] is False and any("modificado" in p for p in report["problems"])
    blocked = api.client.get(final, headers=auth("ana"))
    assert blocked.status_code == 409 and blocked.json()["error"] == "export_integrity_error"


# --------------------------------------------------------------------------- #
# Otros endpoints y transversales
# --------------------------------------------------------------------------- #


def test_templates_and_knowledge(api: Api, tmp_path: Path) -> None:
    templates = api.client.get("/templates", headers=auth("ana")).json()
    by_modality = {t["modality"]: t for t in templates}
    assert by_modality["INDETERMINATE"]["available"] and len(by_modality["INDETERMINATE"]["required_fields"]) == 17
    assert not by_modality["FIXED_TERM"]["available"]

    answer = api.client.post("/knowledge/query", json={"question": "¿Qué dice sobre confidencialidad?"}, headers=auth("ana"))
    assert answer.status_code == 200 and answer.json()["sources"] == ["clausula:SEXTA"] and answer.json()["found"]
    assert api.client.post("/knowledge/query", json={"question": "x"}, headers=auth("ana")).status_code == 422
    assert api.client.post("/knowledge/query", json={"question": "hola"}).status_code == 401

    no_rag = build_api(tmp_path / "sin-rag", with_rag=False)
    assert no_rag.client.post("/knowledge/query", json={"question": "hola mundo"}, headers=auth("ana")).status_code == 503


def test_internal_errors_do_not_leak_details(api: Api) -> None:
    contract_id = api.create()
    api.fill(contract_id)
    api.services.exporter._converter = FakePdfConverter(fail=True)  # type: ignore[attr-defined]
    response = api.client.get(f"/contracts/{contract_id}/document?version=draft", headers=auth("ana"))
    assert response.status_code == 500 and response.json()["error"] == "render_failed"
    assert "conversión simulada" not in response.text


def test_unknown_contract_and_bad_ids(api: Api) -> None:
    assert api.client.get("/contracts/00000000-0000-0000-0000-000000000000", headers=auth("ana")).status_code == 404
    assert api.client.get("/contracts/no-es-uuid", headers=auth("ana")).status_code == 422


def test_cors_allows_only_configured_origins(api: Api) -> None:
    allowed = api.client.options(
        "/contracts",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-api-key"},
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    denied = api.client.options(
        "/contracts", headers={"Origin": "http://sitio-malo.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in denied.headers


def test_openapi_documents_the_api_key_scheme(api: Api) -> None:
    schema = api.client.get("/openapi.json").json()
    assert "APIKeyHeader" in schema["components"]["securitySchemes"]
    assert "/contracts/{contract_id}/review" in schema["paths"]


def test_contract_locks_serialize_the_same_contract_only() -> None:
    import threading
    import time
    from uuid import uuid4

    from app.api.deps import ContractLocks

    locks = ContractLocks()
    same, other = uuid4(), uuid4()
    inside: list[str] = []
    overlap: list[bool] = []

    def worker(contract_id: UUID, name: str) -> None:
        with locks.hold(contract_id):
            overlap.append(len(inside) > 0)
            inside.append(name)
            time.sleep(0.05)
            inside.remove(name)

    threads = [threading.Thread(target=worker, args=(same, f"t{i}")) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert overlap == [False] * 4  # nunca dos a la vez sobre el mismo contrato

    with locks.hold(same):  # otro contrato no queda bloqueado
        with locks.hold(other):
            pass
