"""Comandos de mantenimiento: ``uv run python -m app.cli <comando>``.

- ``index``: reindexa cláusulas y documentos de la carpeta de conocimiento.
- ``ask "pregunta"``: consulta la base de conocimiento.
- ``seed ARCHIVO...``: copia archivos a la carpeta de conocimiento.
- ``apikey NOMBRE ROL``: genera una API key y la entrada para ``HUMANIA_API_USERS``.
- ``chat``: conversa con el agente en la terminal (``/adjuntar RUTA`` sube un archivo,
  ``/salir`` termina).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional, Sequence

from app.agent.service import AgentService
from app.api.auth import generate_api_key
from app.container import build_services
from app.core.config import get_settings
from app.core.exceptions import HumanIAError, UnsupportedDocumentError
from app.services.document_loader import DocumentLoader, LoadedDocument
from app.services.knowledge_loader import seed_knowledge
from app.services.rag_service import build_rag_service


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("index", help="Reindexa la base de conocimiento")
    ask = commands.add_parser("ask", help="Consulta la base de conocimiento")
    ask.add_argument("question")
    seed = commands.add_parser("seed", help="Copia archivos a la carpeta de conocimiento")
    seed.add_argument("files", nargs="+", type=Path)
    commands.add_parser("chat", help="Conversa con el agente")
    apikey = commands.add_parser("apikey", help="Genera una API key y su entrada de configuración")
    apikey.add_argument("name")
    apikey.add_argument("role", choices=["REQUESTER", "REVIEWER"])
    args = parser.parse_args(argv)

    if args.command == "apikey":
        key, digest = generate_api_key()
        entry = {"name": args.name, "role": args.role, "key_sha256": digest}
        print(f"API key (se muestra una sola vez): {key}")
        print(f"Entrada para HUMANIA_API_USERS: {json.dumps(entry)}")
        return 0

    settings = get_settings()

    if args.command == "seed":
        copied = seed_knowledge(args.files, settings.knowledge_dir)
        print(f"Copiados {len(copied)} de {len(args.files)} archivos a {settings.knowledge_dir}")
        return 0

    if args.command == "chat":
        return _chat(build_services(settings).agent)

    service = build_rag_service(settings)
    if args.command == "index":
        report = service.rebuild()
        print(f"Indexados {report.chunks_indexed} fragmentos de: {', '.join(report.sources)}")
        for item in report.skipped:
            print(f"  omitido: {item}")
        return 0

    answer = service.answer(args.question)
    print(answer.answer)
    sources: List[str] = [f"{hit.source} ({hit.score:.2f})" for hit in answer.sources]
    if sources:
        print("\nFuentes: " + "; ".join(sources))
    return 0 if answer.found else 1


def _chat(agent: AgentService) -> int:
    """Bucle de conversación simple sobre un contrato nuevo."""
    loader = DocumentLoader()
    contract = agent.start("cli")
    print(f"Contrato {contract.id}. Escribí tu mensaje (/adjuntar RUTA, /salir).")
    while True:
        try:
            line = input("\n> ").strip()
        except EOFError:
            return 0
        if line in {"/salir", "/exit"}:
            return 0
        documents: List[LoadedDocument] = []
        message = line
        if line.startswith("/adjuntar "):
            path = Path(line.removeprefix("/adjuntar ").strip()).expanduser()
            try:
                documents.append(loader.load(path.read_bytes(), path.name))
            except (OSError, UnsupportedDocumentError) as exc:
                print(f"No pude leer el archivo: {exc}")
                continue
            message = ""
        try:
            reply = agent.handle_message(contract.id, message, "cli", documents)
        except HumanIAError as exc:
            print(f"Error: {exc.message}")
            continue
        print(f"\n{reply.text}")
        for artifact in reply.artifacts:
            print(f"[archivo] {artifact}")


if __name__ == "__main__":
    raise SystemExit(main())
