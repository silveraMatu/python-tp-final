import type { ApiErrorBody } from "./types";

export const BASE_URL: string = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);

const STORAGE_KEY = "humania.session";

/** Error de la API con la forma `{ error, detail }` (o de red, con `status` 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter: number | null;

  constructor(status: number, code: string, detail: string, retryAfter: number | null = null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

// --- Sesión: la API key vive en memoria y, para sobrevivir a una recarga, en sessionStorage. ---
// Nunca en localStorage, URLs ni logs.

let apiKey: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function loadStoredKey(): string | null {
  try {
    const stored = window.sessionStorage.getItem(STORAGE_KEY);
    if (stored) apiKey = stored;
  } catch {
    /* sessionStorage no disponible: queda solo en memoria */
  }
  return apiKey;
}

export function setApiKey(key: string | null): void {
  apiKey = key;
  try {
    if (key) window.sessionStorage.setItem(STORAGE_KEY, key);
    else window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignorar */
  }
}

export function getApiKey(): string | null {
  return apiKey;
}

/** Se invoca ante cualquier 401 de una sesión ya iniciada. */
export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

function parseRetryAfter(res: Response): number | null {
  const raw = res.headers.get("Retry-After");
  const seconds = raw ? Number.parseInt(raw, 10) : Number.NaN;
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

/** Convierte una respuesta no exitosa en un `ApiError` (misma forma `{error, detail}`). */
export async function toApiError(res: Response): Promise<ApiError> {
  let code = `http_${res.status}`;
  let detail = res.statusText || "Error";
  try {
    const body = (await res.json()) as Partial<ApiErrorBody> & { detail?: unknown };
    if (typeof body.error === "string") code = body.error;
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    /* cuerpo vacío o no JSON */
  }
  return new ApiError(res.status, code, detail, parseRetryAfter(res));
}

interface RequestOptions {
  method?: "GET" | "POST";
  json?: unknown;
  form?: FormData;
  /** Key explícita (solo el ingreso, antes de tener sesión). */
  key?: string;
  signal?: AbortSignal;
  /** No cerrar sesión ante un 401 (lo usa el ingreso). */
  skipUnauthorizedHandler?: boolean;
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = {};
  const key = options.key ?? apiKey;
  if (key) headers["X-API-Key"] = key;
  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form; // el navegador agrega el boundary de multipart
  } else if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers,
      body,
      signal: options.signal,
      cache: "no-store",
      credentials: "omit",
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "network_error", "No pudimos conectar con el servidor");
  }
  if (!res.ok) {
    const error = await toApiError(res);
    if (res.status === 401 && !options.skipUnauthorizedHandler) unauthorizedHandler?.();
    throw error;
  }
  return res;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const res = await send(path, options);
  return (await res.json()) as T;
}

export interface BlobResult {
  blob: Blob;
  code: string | null;
  name: string | null;
}

export function parseFilename(disposition: string): string | null {
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  if (!match?.[1]) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

/** Archivos protegidos: se piden con la key y se muestran desde un `blob:`. */
export async function fetchBlob(path: string, signal?: AbortSignal): Promise<BlobResult> {
  if (!isSafeApiPath(path)) throw new ApiError(0, "invalid_path", "Ruta no permitida");
  const res = await send(path, { signal });
  return {
    blob: await res.blob(),
    code: res.headers.get("X-Verification-Code"),
    name: parseFilename(res.headers.get("Content-Disposition") ?? ""),
  };
}

/** Solo se siguen rutas relativas de contratos (`url` de adjuntos y documentos). */
export function isSafeApiPath(path: string): boolean {
  return path.startsWith("/contracts/") && !path.includes("..") && !path.includes("//");
}
