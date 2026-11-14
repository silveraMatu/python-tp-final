# API keys de demostración

Estas keys son **públicas y solo sirven para uso local**. Se crean con el comando `demo-seed`
(definidas en `app/demo.py`). No las uses en ningún entorno real.

## Usuarios de demo

| Usuario | Rol | API key | Qué puede hacer |
|---|---|---|---|
| ana | REQUESTER (solicitante) | `demo-ana-key` | Crear contratos, chatear con el asistente, adjuntar archivos, enviar a revisión, descargar el documento final. Solo ve sus contratos. |
| carlos | REQUESTER (solicitante) | `demo-carlos-key` | Igual que ana, pero con sus propios contratos (sirve para probar que ana no ve los de carlos). |
| bruno | REVIEWER (revisor) | `demo-bruno-key` | Ve la bandeja de revisión y todos los contratos; aprueba, rechaza o pide cambios. No usa el chat. |

## Cómo se usan

- Frontend: pegar la key en la pantalla de ingreso.
- API: enviar el header `X-API-Key`. Ejemplo:

```bash
curl -H "X-API-Key: demo-ana-key" http://127.0.0.1:8000/me
```

## Cómo se generan los datos

```bash
uv run python -m app.cli demo-seed --force
uv run uvicorn app.api.main:app --env-file data/demo/demo.env
```

`demo-seed` crea `data/demo/` con una base de datos, contratos en cada estado y un `demo.env`.
En ese archivo solo se guardan los **hashes SHA-256** de las keys (la API nunca guarda la key en claro),
por eso al abrirlo no vas a ver `demo-ana-key`.

## ¿Son las únicas keys del proyecto?

No. Son las únicas **de demostración**, pero existen otras:

1. **Keys propias para uso real.** Se generan con
   `uv run python -m app.cli apikey NOMBRE REQUESTER|REVIEWER`. El comando muestra la key una sola vez
   y la entrada con su hash para la variable `HUMANIA_API_USERS` (ver `.env.example`).
2. **Ollama.** Para los modelos `:cloud` hay que iniciar sesión en Ollama (`ollama signin`); no es una
   API key del proyecto y no se guarda en el repositorio.
3. **Keys de prueba en los tests** (`tests/test_api.py`). Usan valores fijos de prueba (`key-ana`, `key-carlos`, `key-bruno`) que solo existen dentro de los tests.

El proyecto no usa claves de OpenAI, Google ni otros proveedores externos.
