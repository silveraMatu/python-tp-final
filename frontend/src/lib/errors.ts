import { ApiError } from "../api/client";

/** Traduce un error de la API a un texto claro. Nunca muestra JSON crudo ni trazas. */
export function describeError(err: unknown): string {
  if (!(err instanceof ApiError)) return "Ocurrió un error inesperado. Probá de nuevo.";
  switch (err.code) {
    case "network_error":
      return "No pudimos conectar con el servidor.";
    case "unauthorized":
      return "Tu sesión ya no es válida.";
    case "forbidden":
      return "No tenés acceso a esto.";
    case "contract_not_found":
    case "not_found":
      return "Contrato no encontrado.";
    case "invalid_state_transition":
    case "no_pending_conflict":
      return err.message;
    case "export_integrity_error":
      return "Este documento no pasó la verificación de integridad. No lo uses y avisá al área de sistemas.";
    case "payload_too_large":
      return err.message;
    case "validation_error":
      return err.message;
    case "incomplete_contract":
      return "Todavía faltan datos para generar el borrador.";
    case "unsupported_document":
      return "Ese archivo no se puede leer.";
    case "rate_limited":
      return err.retryAfter
        ? `Demasiados intentos seguidos. Probá de nuevo en ${err.retryAfter} segundos.`
        : "Demasiados intentos seguidos. Esperá un momento.";
    case "unsupported_modality":
      return "Esa modalidad de contrato todavía no tiene una plantilla aprobada.";
    case "extraction_failed":
      return "No pudimos interpretar tu mensaje. Probá de nuevo.";
    case "llm_unavailable":
    case "service_unavailable":
      return "El asistente no está disponible por ahora.";
    case "render_failed":
    case "template_not_found":
    case "internal_error":
      return "No pudimos generar el documento. Probá de nuevo.";
    default:
      if (err.status >= 500) return "Hubo un problema en el servidor. Probá de nuevo.";
      return err.message || "Ocurrió un error inesperado.";
  }
}

export function isAuthError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401;
}

export function isStateConflict(err: unknown): boolean {
  return err instanceof ApiError && err.status === 409;
}

export function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

export function isAssistantUnavailable(err: unknown): boolean {
  return err instanceof ApiError && (err.code === "llm_unavailable" || err.code === "service_unavailable");
}
