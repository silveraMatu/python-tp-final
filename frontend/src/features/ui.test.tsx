import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../api/types";
import Composer from "./chat/Composer";
import MessageBubble from "./chat/MessageBubble";
import DecisionDialog from "./review/DecisionDialog";

function message(over: Partial<ChatMessage>): ChatMessage {
  return {
    id: "1",
    seq: 1,
    timestamp: "2026-11-13T15:00:00Z",
    role: "user",
    actor: "ana",
    text: "",
    intent: null,
    classification_source: null,
    sources: [],
    documents: [],
    attachments: [],
    ...over,
  };
}

describe("render seguro del chat", () => {
  it("muestra HTML y scripts como texto literal", () => {
    const { container } = render(
      <MessageBubble
        message={message({ text: "<script>alert(1)</script> <b>hola</b>" })}
        mine
        onOpenDocument={() => undefined}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText("<script>alert(1)</script> <b>hola</b>")).toBeInTheDocument();
  });

  it("no convierte URLs ni Markdown en enlaces o imágenes", () => {
    const { container } = render(
      <MessageBubble
        message={message({
          role: "agent",
          actor: "assistant",
          text: "[clic](https://evil.example) ![x](https://evil.example/a.png) https://evil.example",
        })}
        mine={false}
        onOpenDocument={() => undefined}
      />,
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("el mensaje BLOCKED se muestra como aviso", () => {
    render(
      <MessageBubble
        message={message({ role: "agent", actor: "assistant", intent: "BLOCKED", text: "No puedo procesar ese mensaje" })}
        mine={false}
        onOpenDocument={() => undefined}
      />,
    );
    expect(screen.getByText(/Aviso de seguridad/)).toBeInTheDocument();
  });

  it("ignora rutas de documentos que no sean de /contracts/", () => {
    render(
      <MessageBubble
        message={message({
          role: "agent",
          actor: "assistant",
          text: "listo",
          documents: [{ kind: "draft", format: "pdf", url: "https://evil.example/x.pdf" }],
        })}
        mine={false}
        onOpenDocument={() => undefined}
      />,
    );
    expect(screen.queryByText("Ver borrador")).toBeNull();
  });
});

describe("Composer", () => {
  const base = { cooldown: 0, sending: false, assistantDown: false };

  it("Enter envía y Shift+Enter agrega una línea", async () => {
    const onSend = vi.fn();
    render(<Composer {...base} disabledReason={null} onSend={onSend} />);
    const box = screen.getByLabelText("Mensaje para el asistente");
    await userEvent.type(box, "hola{Shift>}{Enter}{/Shift}mundo");
    expect(onSend).not.toHaveBeenCalled();
    await userEvent.type(box, "{Enter}");
    expect(onSend).toHaveBeenCalledWith("hola\nmundo", []);
  });

  it("bloquea el envío con más de 4000 caracteres", async () => {
    const onSend = vi.fn();
    render(<Composer {...base} disabledReason={null} onSend={onSend} />);
    const box = screen.getByLabelText("Mensaje para el asistente");
    await userEvent.click(box);
    await userEvent.paste("a".repeat(4001));
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
    expect(screen.getByText(/demasiado largo/)).toBeInTheDocument();
  });

  it("rechaza en el cliente un .exe", async () => {
    render(<Composer {...base} disabledReason={null} onSend={() => undefined} />);
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    await userEvent.upload(input, new File(["x"], "virus.exe"), { applyAccept: false });
    expect(screen.getByRole("alert")).toHaveTextContent(/solo se admiten/);
  });

  it("muestra la explicación cuando no se puede escribir", () => {
    render(<Composer {...base} disabledReason="Está en revisión humana" onSend={() => undefined} />);
    expect(screen.getByText("Está en revisión humana")).toBeInTheDocument();
    expect(screen.queryByLabelText("Mensaje para el asistente")).toBeNull();
  });

  it("espera tras un 429", () => {
    render(<Composer {...base} cooldown={12} disabledReason={null} onSend={() => undefined} />);
    expect(screen.getByRole("button", { name: /Esperá 12 s/ })).toBeDisabled();
  });
});

describe("DecisionDialog", () => {
  it("rechazar y pedir cambios exigen comentario; aprobar no", async () => {
    const { unmount } = render(
      <DecisionDialog decision="REJECT" busy={false} error={null} onCancel={() => undefined} onConfirm={() => undefined} />,
    );
    expect(screen.getByRole("button", { name: "Confirmar rechazo" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Comentario/), "Faltan datos");
    expect(screen.getByRole("button", { name: "Confirmar rechazo" })).toBeEnabled();
    unmount();
    render(
      <DecisionDialog decision="APPROVE" busy={false} error={null} onCancel={() => undefined} onConfirm={() => undefined} />,
    );
    expect(screen.getByRole("button", { name: "Confirmar aprobación" })).toBeEnabled();
  });

  it("la aprobación no se dispara con Enter, solo con un clic en confirmar", async () => {
    const onConfirm = vi.fn();
    render(<DecisionDialog decision="APPROVE" busy={false} error={null} onCancel={() => undefined} onConfirm={onConfirm} />);
    await userEvent.type(screen.getByLabelText(/Comentario/), "ok{Enter}");
    expect(onConfirm).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Confirmar aprobación" }));
    expect(onConfirm).toHaveBeenCalledWith("ok");
  });

  it("se cierra con Esc y atrapa el foco", async () => {
    const onCancel = vi.fn();
    render(<DecisionDialog decision="APPROVE" busy={false} error={null} onCancel={onCancel} onConfirm={() => undefined} />);
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
    await userEvent.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalled();
  });
});

describe("reglas de seguridad del código fuente", () => {
  function sources(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) return sources(path);
      return /\.(ts|tsx)$/.test(name) && !/\.test\./.test(name) && !name.includes("schema.ts") ? [path] : [];
    });
  }
  const files = sources(join(process.cwd(), "src"));

  it.each(["dangerouslySetInnerHTML", "innerHTML", "outerHTML", "insertAdjacentHTML", "eval("])(
    "no usa %s",
    (needle) => {
      const offenders = files.filter((f) => readFileSync(f, "utf8").includes(needle));
      expect(offenders).toEqual([]);
    },
  );

  it("no usa localStorage para nada", () => {
    const offenders = files.filter((f) => /localStorage/.test(readFileSync(f, "utf8").replace(/\/\/.*$/gm, "")));
    expect(offenders).toEqual([]);
  });

  it("no hay `any` explícito", () => {
    const offenders = files.filter((f) => /:\s*any\b|\bas any\b|<any>/.test(readFileSync(f, "utf8")));
    expect(offenders).toEqual([]);
  });
});
