# HumanIA – Agente de contratos laborales

Backend determinista (FastAPI + Pydantic v2) que arma contratos de trabajo a partir de lenguaje
natural y documentos. El LLM solo extrae y clasifica; las cláusulas son las aprobadas por la
empresa y la aprobación es siempre una decisión humana.

## Puesta en marcha

```bash
uv sync
cp .env.example .env                       # ajustar variables HUMANIA_*
ollama pull nomic-embed-text               # embeddings locales (RAG)
uv run python -m app.cli apikey ana REQUESTER   # genera una API key (se muestra una vez)
uv run python -m app.cli apikey bruno REVIEWER
# pegar las entradas impresas en HUMANIA_API_USERS dentro de .env
uv run uvicorn app.api.main:app --reload   # documentación interactiva en /docs
```

Requisitos: Python 3.11+, [uv](https://docs.astral.sh/uv/), Ollama (con un modelo `:cloud` con
créditos, o uno local), LibreOffice (`soffice`) para generar PDF.

## Flujo

1. `REQUESTER`: `POST /contracts` → `POST /contracts/{id}/messages` (texto y/o archivos) hasta que
   los datos estén completos → `GET .../document?version=draft` (PDF con marca de borrador) →
   `POST .../submit`.
2. `REVIEWER`: `POST /contracts/{id}/review` con `APPROVE`, `REJECT` o `REQUEST_CHANGES`.
3. Aprobado: `GET .../document?version=final&format=pdf|docx` (se emite una sola vez) y
   `GET .../verification` para comprobar que no fue alterado.

Autenticación: header `X-API-Key`. Un solicitante solo ve sus contratos; un revisor ve los que
llegaron a revisión.

## Comandos útiles

```bash
uv run pytest                      # tests unitarios (sin red)
uv run pytest -m integration       # contra Ollama real
uv run python -m app.cli chat      # conversar con el agente en la terminal
uv run python -m app.cli index     # reindexar la base de conocimiento (RAG)
```
