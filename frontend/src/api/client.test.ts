import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  fetchBlob,
  isSafeApiPath,
  onUnauthorized,
  parseFilename,
  request,
  setApiKey,
} from "./client";

const realFetch = globalThis.fetch;

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

beforeEach(() => {
  window.sessionStorage.clear();
  setApiKey("k-prueba");
});
afterEach(() => {
  globalThis.fetch = realFetch;
  onUnauthorized(null);
  setApiKey(null);
});

describe("cliente HTTP", () => {
  it("envía X-API-Key en cada pedido y no usa cookies", async () => {
    const spy = vi.fn().mockResolvedValue(json(200, { ok: true }));
    globalThis.fetch = spy as typeof fetch;
    await request("/me");
    const init = spy.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-API-Key"]).toBe("k-prueba");
    expect(init.credentials).toBe("omit");
  });

  it("guarda la key solo en sessionStorage, nunca en localStorage", () => {
    expect(window.sessionStorage.getItem("humania.session")).toBe("k-prueba");
    expect(window.localStorage.length).toBe(0);
  });

  it("convierte errores {error, detail} en ApiError con Retry-After", async () => {
    globalThis.fetch = (async () =>
      json(429, { error: "rate_limited", detail: "Esperá" }, { "Retry-After": "37" })) as typeof fetch;
    await expect(request("/x")).rejects.toMatchObject({ status: 429, code: "rate_limited", retryAfter: 37 });
  });

  it("ante un 401 avisa para cerrar la sesión", async () => {
    const handler = vi.fn();
    onUnauthorized(handler);
    globalThis.fetch = (async () => json(401, { error: "unauthorized", detail: "no" })) as typeof fetch;
    await expect(request("/me")).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("el ingreso con una key mala no cierra la sesión de otra pantalla", async () => {
    const handler = vi.fn();
    onUnauthorized(handler);
    globalThis.fetch = (async () => json(401, { error: "unauthorized", detail: "no" })) as typeof fetch;
    await expect(request("/me", { key: "mala", skipUnauthorizedHandler: true })).rejects.toBeInstanceOf(ApiError);
    expect(handler).not.toHaveBeenCalled();
  });

  it("un fallo de red es un ApiError con status 0", async () => {
    globalThis.fetch = (async () => {
      throw new TypeError("Failed to fetch");
    }) as typeof fetch;
    await expect(request("/x")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("no reintenta solo un POST", async () => {
    const spy = vi.fn().mockResolvedValue(json(503, { error: "llm_unavailable", detail: "x" }));
    globalThis.fetch = spy as typeof fetch;
    await expect(request("/contracts/1/messages", { method: "POST", form: new FormData() })).rejects.toBeDefined();
    expect(spy).toHaveBeenCalledOnce();
  });
});

describe("descargas", () => {
  it("lee el código de verificación y el nombre del archivo", async () => {
    globalThis.fetch = (async () =>
      new Response("%PDF-1.4", {
        status: 200,
        headers: {
          "X-Verification-Code": "4E48-7A72-658D",
          "Content-Disposition": 'attachment; filename="borrador-123.pdf"',
        },
      })) as typeof fetch;
    const result = await fetchBlob("/contracts/123/document?version=draft&format=pdf");
    expect(result.code).toBe("4E48-7A72-658D");
    expect(result.name).toBe("borrador-123.pdf");
  });

  it("solo sigue rutas relativas de contratos", async () => {
    expect(isSafeApiPath("/contracts/abc/attachments/def")).toBe(true);
    expect(isSafeApiPath("https://evil.example/x")).toBe(false);
    expect(isSafeApiPath("//evil.example/contracts/")).toBe(false);
    expect(isSafeApiPath("/contracts/../admin")).toBe(false);
    await expect(fetchBlob("https://evil.example/x")).rejects.toMatchObject({ code: "invalid_path" });
  });

  it("parseFilename entiende filename y filename*", () => {
    expect(parseFilename("attachment; filename*=UTF-8''contrato%20final.pdf")).toBe("contrato final.pdf");
    expect(parseFilename("")).toBeNull();
  });
});
