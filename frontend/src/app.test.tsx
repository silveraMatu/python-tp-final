import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { setApiKey } from "./api/client";
import type { AllowedAction, ChatMessage, Contract } from "./api/types";
import { AuthProvider } from "./auth/AuthContext";

type Handler = (req: { url: URL; method: string; body: BodyInit | null | undefined }) => Response | Promise<Response>;

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

let routes: Array<[RegExp, Handler]> = [];
let calls: string[] = [];

function route(method: string, pattern: RegExp, handler: Handler) {
  routes.push([new RegExp(`^${method} ${pattern.source}$`), handler]);
}

beforeEach(() => {
  routes = [];
  calls = [];
  window.sessionStorage.clear();
  setApiKey(null);
  URL.createObjectURL = vi.fn(() => "blob:fake");
  URL.revokeObjectURL = vi.fn();
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const key = `${method} ${url.pathname}${url.search}`;
    calls.push(key);
    for (const [pattern, handler] of routes) {
      if (pattern.test(key)) return handler({ url, method, body: init?.body });
    }
    return json(404, { error: "not_found", detail: `sin ruta simulada: ${key}` });
  }) as typeof fetch;
});
afterEach(() => setApiKey(null));

const ID = "11111111-1111-4111-8111-111111111111";

function contract(over: Partial<Contract> = {}): Contract {
  return {
    id: ID,
    status: "COLLECTING_DATA",
    status_label: "Recolectando datos",
    created_by: "ana",
    is_complete: false,
    missing_fields: ["employee.cuil", "company.cuit"],
    fields: [{ field_name: "employee.nombre", label: "Nombre del empleado/a", value: "Juan" }],
    pending_conflicts: [],
    issues: [],
    allowed_actions: ["send_message"] as AllowedAction[],
    ...over,
  };
}

function msg(seq: number, over: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: `m${seq}`,
    seq,
    timestamp: "2026-11-13T15:00:00Z",
    role: "user",
    actor: "ana",
    text: `mensaje ${seq}`,
    intent: null,
    classification_source: null,
    sources: [],
    documents: [],
    attachments: [],
    ...over,
  };
}

function mount(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function signedIn(user: "ana" | "bruno") {
  setApiKey(`key-${user}`);
  route("GET", /\/me/, () =>
    json(200, { name: user, role: user === "ana" ? "REQUESTER" : "REVIEWER" }),
  );
}

describe("ingreso", () => {
  it("muestra el error de key inválida y luego entra a «Mis contratos»", async () => {
    route("GET", /\/me/, ({ url }) => url.pathname === "/me" ? json(401, { error: "unauthorized", detail: "no" }) : json(404, {}));
    route("GET", /\/contracts/, () => json(200, []));
    mount("/");
    await userEvent.type(await screen.findByLabelText("API key"), "mala");
    await userEvent.click(screen.getByRole("button", { name: "Ingresar" }));
    expect(await screen.findByText("La API key no es válida.")).toBeInTheDocument();

    routes = [];
    route("GET", /\/me/, () => json(200, { name: "ana", role: "REQUESTER" }));
    route("GET", /\/contracts/, () => json(200, [contract()]));
    await userEvent.clear(screen.getByLabelText("API key"));
    await userEvent.type(screen.getByLabelText("API key"), "demo-ana-key");
    await userEvent.click(screen.getByRole("button", { name: "Ingresar" }));
    expect(await screen.findByRole("heading", { name: "Mis contratos" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("humania.session")).toBe("demo-ana-key");
    expect(window.localStorage.length).toBe(0);
    expect(await screen.findByText("Juan")).toBeInTheDocument();
  });

  it("el 429 muestra la espera", async () => {
    route("GET", /\/me/, () => json(429, { error: "rate_limited", detail: "x" }, { "Retry-After": "37" }));
    mount("/");
    await userEvent.type(await screen.findByLabelText("API key"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Ingresar" }));
    expect(await screen.findByText(/37 segundos/)).toBeInTheDocument();
  });

  it("un 401 con la sesión iniciada vuelve al ingreso con aviso y limpia la key", async () => {
    signedIn("ana");
    routes.pop();
    let first = true;
    route("GET", /\/me/, () => {
      if (first) {
        first = false;
        return json(200, { name: "ana", role: "REQUESTER" });
      }
      return json(401, { error: "unauthorized", detail: "no" });
    });
    route("GET", /\/contracts/, () => json(401, { error: "unauthorized", detail: "no" }));
    mount("/contratos");
    expect(await screen.findByText("Tu sesión ya no es válida.")).toBeInTheDocument();
    expect(window.sessionStorage.getItem("humania.session")).toBeNull();
  });

  it("un revisor que abre una ruta de solicitante ve «No tenés acceso»", async () => {
    signedIn("bruno");
    route("GET", /\/contracts/, () => json(200, []));
    mount("/contratos");
    expect(await screen.findByText("No tenés acceso a esta sección")).toBeInTheDocument();
  });
});

describe("detalle del solicitante", () => {
  it("envía un mensaje, agrega ambos mensajes y actualiza el panel sin recargar", async () => {
    signedIn("ana");
    route("GET", new RegExp(`/contracts/${ID}`), () => json(200, contract()));
    route("GET", new RegExp(`/contracts/${ID}/messages\\?limit=50.*`), () =>
      json(200, { items: [msg(1, { text: "hola previo" })], has_more: false, next_before: null }),
    );
    route("POST", new RegExp(`/contracts/${ID}/messages`), () =>
      json(200, {
        reply: "Registré 3 dato(s)",
        intent: "PROVIDE_DATA",
        classification_source: "llm",
        contract: contract({
          fields: [
            { field_name: "employee.nombre", label: "Nombre del empleado/a", value: "Juan" },
            { field_name: "employee.dni", label: "DNI del empleado/a", value: "30.123.456" },
          ],
          missing_fields: ["employee.cuil"],
        }),
        documents: [],
        sources: [],
        user_message: msg(2, { text: "El empleado se llama Juan Pérez" }),
        agent_message: msg(3, { role: "agent", actor: "assistant", text: "Registré 3 dato(s)", intent: "PROVIDE_DATA" }),
      }),
    );
    mount(`/contratos/${ID}`);
    expect(await screen.findByText("hola previo")).toBeInTheDocument();
    expect(screen.getByText("15/17 datos")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Mensaje para el asistente"), "El empleado se llama Juan Pérez{Enter}");
    expect(await screen.findByText("Registré 3 dato(s)")).toBeInTheDocument();
    expect(screen.getByText("El empleado se llama Juan Pérez")).toBeInTheDocument();
    expect(await screen.findByText("16/17 datos")).toBeInTheDocument();
    expect(screen.getByText("30.123.456")).toBeInTheDocument();
    // no se hizo otro GET del contrato para refrescar: se usó el que devolvió el POST
    expect(calls.filter((c) => c === `GET /contracts/${ID}`)).toHaveLength(1);
  });

  it("ante un 503 marca el mensaje como no enviado y el reintento es manual", async () => {
    signedIn("ana");
    route("GET", new RegExp(`/contracts/${ID}$`), () => json(200, contract()));
    route("GET", new RegExp(`/contracts/${ID}/messages.*`), () => json(200, { items: [], has_more: false, next_before: null }));
    let attempts = 0;
    route("POST", new RegExp(`/contracts/${ID}/messages`), () => {
      attempts += 1;
      if (attempts === 1) return json(503, { error: "llm_unavailable", detail: "sin créditos" });
      return json(200, {
        reply: "ok",
        intent: "SMALL_TALK",
        classification_source: "llm",
        contract: contract(),
        documents: [],
        sources: [],
        user_message: msg(1, { text: "hola" }),
        agent_message: msg(2, { role: "agent", actor: "assistant", text: "Hola" }),
      });
    });
    mount(`/contratos/${ID}`);
    await userEvent.type(await screen.findByLabelText("Mensaje para el asistente"), "hola{Enter}");
    expect(await screen.findByText(/No se pudo enviar/)).toBeInTheDocument();
    expect(screen.getByText(/El asistente no está disponible por ahora; podés seguir/)).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(attempts).toBe(1); // nunca reintenta solo
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("Hola")).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("deshabilita el compositor en revisión humana pero deja ver el chat", async () => {
    signedIn("ana");
    route("GET", new RegExp(`/contracts/${ID}$`), () =>
      json(200, contract({ status: "PENDING_HUMAN_REVIEW", status_label: "Pendiente de revisión humana", allowed_actions: ["get_draft"] })),
    );
    route("GET", new RegExp(`/contracts/${ID}/messages.*`), () =>
      json(200, { items: [msg(1, { text: "un mensaje viejo" })], has_more: false, next_before: null }),
    );
    mount(`/contratos/${ID}`);
    expect(await screen.findByText("un mensaje viejo")).toBeInTheDocument();
    expect(screen.getByText(/Está en revisión humana/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Mensaje para el asistente")).toBeNull();
    expect(screen.getByText(/Enviado a revisión humana/)).toBeInTheDocument();
  });

  it("confirma un dato pendiente con el botón y desaparece el banner", async () => {
    signedIn("ana");
    const pending = contract({
      status: "CONFLICT_DETECTED",
      status_label: "Esperando confirmación de un dato",
      allowed_actions: ["send_message", "resolve_conflict"],
      pending_conflicts: [{ field_name: "employee.dni", label: "DNI del empleado/a", value: "30.123.456", detail: "Confianza 0.55 por debajo del umbral 0.80" }],
    });
    route("GET", new RegExp(`/contracts/${ID}$`), () => json(200, pending));
    route("GET", new RegExp(`/contracts/${ID}/messages.*`), () => json(200, { items: [], has_more: false, next_before: null }));
    route("POST", new RegExp(`/contracts/${ID}/conflicts/resolve`), ({ body }) => {
      expect(JSON.parse(String(body))).toEqual({ field_name: "employee.dni", accept_new: true });
      return json(200, contract({ fields: [{ field_name: "employee.dni", label: "DNI del empleado/a", value: "30.123.456" }] }));
    });
    mount(`/contratos/${ID}`);
    expect(await screen.findByText(/Hay datos pendientes de tu confirmación/)).toBeInTheDocument();
    expect(screen.getByText(/Confianza 0.55/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Usar este valor" }));
    await waitFor(() => expect(screen.queryByText(/Hay datos pendientes de tu confirmación/)).toBeNull());
    expect(calls.filter((c) => c.startsWith(`GET /contracts/${ID}/messages`)).length).toBeGreaterThanOrEqual(2);
  });

  it("un contrato ajeno muestra «Contrato no encontrado»", async () => {
    signedIn("ana");
    route("GET", new RegExp(`/contracts/${ID}$`), () => json(404, { error: "contract_not_found", detail: "x" }));
    route("GET", new RegExp(`/contracts/${ID}/messages.*`), () => json(404, { error: "contract_not_found", detail: "x" }));
    mount(`/contratos/${ID}`);
    expect(await screen.findByText("Contrato no encontrado")).toBeInTheDocument();
  });
});

describe("revisor", () => {
  function reviewerRoutes() {
    signedIn("bruno");
    const pending = contract({
      status: "PENDING_HUMAN_REVIEW",
      status_label: "Pendiente de revisión humana",
      is_complete: true,
      missing_fields: [],
      allowed_actions: ["get_draft", "review"],
    });
    route("GET", new RegExp(`/contracts/${ID}$`), () => json(200, pending));
    route("GET", new RegExp(`/contracts/${ID}/history`), () =>
      json(200, [{ timestamp: "2026-11-13T15:00:00Z", actor: "ana", action: "submitted_for_review", status: "PENDING_HUMAN_REVIEW", detail: "hash:secreto" }]),
    );
    route("GET", new RegExp(`/contracts/${ID}/document.*`), () =>
      new Response("%PDF-1.4", { status: 200, headers: { "X-Verification-Code": "4E48-7A72-658D", "Content-Disposition": 'attachment; filename="borrador.pdf"' } }),
    );
  }

  it("no muestra chat ni adjuntos, solo datos, borrador e historial (sin detail técnico)", async () => {
    reviewerRoutes();
    mount(`/revision/${ID}`);
    expect(await screen.findByRole("heading", { name: "Datos" })).toBeInTheDocument();
    expect(await screen.findByText("4E48-7A72-658D")).toBeInTheDocument();
    expect(await screen.findByText("Enviado a revisión")).toBeInTheDocument();
    expect(screen.queryByText("hash:secreto")).toBeNull();
    expect(screen.queryByLabelText("Mensaje para el asistente")).toBeNull();
    expect(calls.some((c) => c.includes("/messages") || c.includes("/attachments"))).toBe(false);
  });

  it("aprobar pide confirmación explícita y muestra el aviso", async () => {
    reviewerRoutes();
    let decided: unknown = null;
    route("POST", new RegExp(`/contracts/${ID}/review`), ({ body }) => {
      decided = JSON.parse(String(body));
      return json(200, contract({ status: "APPROVED", status_label: "Aprobado", allowed_actions: ["get_final_document", "verify_final"] }));
    });
    route("GET", new RegExp(`/contracts/${ID}/verification`), () => json(200, { ok: true, problems: [], verification_code: "DF46-5298-E1B1" }));
    mount(`/revision/${ID}`);
    await userEvent.click(await screen.findByRole("button", { name: "Aprobar" }));
    const dialog = await screen.findByRole("dialog");
    expect(decided).toBeNull();
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirmar aprobación" }));
    expect(await screen.findByText(/Aprobaste el contrato/)).toBeInTheDocument();
    expect(decided).toEqual({ decision: "APPROVE", comment: null });
    expect(await screen.findByText(/Documento verificado/)).toBeInTheDocument();
  });

  it("pedir cambios exige comentario y vuelve a la bandeja con aviso", async () => {
    reviewerRoutes();
    route("POST", new RegExp(`/contracts/${ID}/review`), ({ body }) => {
      expect(JSON.parse(String(body))).toEqual({ decision: "REQUEST_CHANGES", comment: "Falta el lugar de trabajo" });
      return json(200, contract());
    });
    route("GET", /\/contracts\?status_filter=PENDING_HUMAN_REVIEW/, () => json(200, []));
    mount(`/revision/${ID}`);
    await userEvent.click(await screen.findByRole("button", { name: "Pedir cambios" }));
    const confirm = screen.getByRole("button", { name: "Confirmar pedido de cambios" });
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Comentario/), "Falta el lugar de trabajo");
    await userEvent.click(confirm);
    expect(await screen.findByText("Pediste cambios. El solicitante lo va a ver en su lista.")).toBeInTheDocument();
    expect(await screen.findByText("No hay contratos pendientes de revisión.")).toBeInTheDocument();
  });

  it("un 409 al decidir recarga el contrato y muestra el detalle", async () => {
    reviewerRoutes();
    route("POST", new RegExp(`/contracts/${ID}/review`), () =>
      json(409, { error: "invalid_state_transition", detail: "Transición de estado no permitida" }),
    );
    mount(`/revision/${ID}`);
    await userEvent.click(await screen.findByRole("button", { name: "Aprobar" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirmar aprobación" }));
    expect(await screen.findByText("Transición de estado no permitida")).toBeInTheDocument();
    await waitFor(() => expect(calls.filter((c) => c === `GET /contracts/${ID}`).length).toBeGreaterThanOrEqual(2));
  });
});
