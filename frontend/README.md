# HumanIA – Frontend

SPA en React 19 + Vite + TypeScript + React Router + TanStack Query, según `docs/GUIA_FRONTEND.md`.

## Requisitos
Node 20+ y el backend corriendo (por defecto `http://127.0.0.1:8000`).

## Uso
```bash
cp .env.example .env      # ajustar VITE_API_URL si hace falta
npm install
npm run dev               # desarrollo
npm run build && npm run preview   # producción local (con CSP)
```

## Tests
```bash
npm run typecheck
npm test                  # unitarios y de componentes (mocks de red)
# Integración contra el backend real (demo sembrada: `demo-seed --force` antes):
VITE_API_URL=http://127.0.0.1:8000 npm run test:integration
```

## Tipos de la API
`npm run gen:api` regenera `src/api/schema.ts` desde `docs/openapi.json`.

## Notas
- La API key vive solo en memoria y `sessionStorage`; nunca en `localStorage`.
- Los mensajes del chat se renderizan como texto plano.
- Los botones salen de `allowed_actions` del backend.
- El chat con el LLM real requiere Ollama; no se probó el render visual en un navegador real.
