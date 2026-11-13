"""Comandos de mantenimiento: ``uv run python -m app.cli <comando>``.

- ``index``: reindexa cláusulas y documentos de la carpeta de conocimiento.
- ``ask "pregunta"``: consulta la base de conocimiento.
- ``seed ARCHIVO...``: copia archivos a la carpeta de conocimiento.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional, Sequence

from app.core.config import get_settings
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
    args = parser.parse_args(argv)

    settings = get_settings()

    if args.command == "seed":
        copied = seed_knowledge(args.files, settings.knowledge_dir)
        print(f"Copiados {len(copied)} de {len(args.files)} archivos a {settings.knowledge_dir}")
        return 0

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


if __name__ == "__main__":
    raise SystemExit(main())
