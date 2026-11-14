import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ApiError, request } from "../../api/client";
import { useSetContract } from "../../api/hooks";
import type { ChatMessage, Contract, MessageResult } from "../../api/types";
import { describeError, isAssistantUnavailable, isAuthError, isStateConflict } from "../../lib/errors";
import { can } from "../../lib/labels";
import Composer from "./Composer";
import type { ChatHistory } from "./useChat";
import MessageBubble, { LocalBubble, type LocalMessage } from "./MessageBubble";

interface Props {
  contract: Contract;
  chat: ChatHistory;
  me: string;
  onOpenDocument: (path: string) => void;
  onContractChanged: () => void;
}

function disabledReasonFor(contract: Contract): string | null {
  if (can(contract.allowed_actions, "send_message")) return null;
  switch (contract.status) {
    case "PENDING_HUMAN_REVIEW":
      return "Está en revisión humana: por ahora no se pueden enviar mensajes.";
    case "APPROVED":
    case "REJECTED":
      return "El contrato ya está cerrado.";
    default:
      return "No se pueden enviar mensajes en este momento.";
  }
}

let localCounter = 0;

export default function ChatPanel({ contract, chat, me, onOpenDocument, onContractChanged }: Props) {
  const setContract = useSetContract();
  const [pending, setPending] = useState<LocalMessage[]>([]);
  const [cooldown, setCooldown] = useState(0);
  const [assistantDown, setAssistantDown] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const prevHeight = useRef(0);
  const lastPrepend = useRef(0);
  const firstScroll = useRef(true);

  const sending = pending.some((item) => item.status === "sending");
  const { messages, prependVersion, loadOlder, hasMore, loading, loadingOlder, error } = chat;

  // Cuenta regresiva tras un 429.
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  // Scroll: abre en el último mensaje, conserva la posición al anteponer y sigue al final al agregar.
  useLayoutEffect(() => {
    const node = logRef.current;
    if (!node) return;
    if (prependVersion !== lastPrepend.current) {
      lastPrepend.current = prependVersion;
      node.scrollTop += node.scrollHeight - prevHeight.current;
    } else if (stick.current || firstScroll.current) {
      node.scrollTop = node.scrollHeight;
      if (messages.length > 0) firstScroll.current = false;
    }
    prevHeight.current = node.scrollHeight;
  }, [messages, pending, prependVersion]);

  function onScroll() {
    const node = logRef.current;
    if (!node) return;
    stick.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
    if (node.scrollTop < 60 && hasMore && !loadingOlder) {
      prevHeight.current = node.scrollHeight;
      void loadOlder();
    }
  }

  const deliver = useCallback(
    async (localId: string, text: string, files: File[]) => {
      const form = new FormData();
      form.append("message", text);
      for (const file of files) form.append("files", file);
      try {
        const result = await request<MessageResult>(`/contracts/${contract.id}/messages`, {
          method: "POST",
          form,
        });
        stick.current = true;
        chat.append(result.user_message, result.agent_message);
        setPending((items) => items.filter((item) => item.localId !== localId));
        setContract(result.contract);
        setAssistantDown(false);
      } catch (err) {
        if (isAuthError(err)) return; // la sesión se cierra sola
        if (err instanceof ApiError && err.status === 429) setCooldown(err.retryAfter ?? 30);
        setAssistantDown(isAssistantUnavailable(err));
        if (isStateConflict(err)) onContractChanged(); // el estado cambió: recargar botones
        setPending((items) =>
          items.map((item) =>
            item.localId === localId
              ? { ...item, status: "failed", error: describeError(err) }
              : item,
          ),
        );
      }
    },
    [chat, contract.id, onContractChanged, setContract],
  );

  function onSend(text: string, files: File[]) {
    const localId = `local-${++localCounter}`;
    stick.current = true;
    setPending((items) => [...items, { localId, text, files, status: "sending" }]);
    void deliver(localId, text, files);
  }

  function retry(item: LocalMessage) {
    setPending((items) =>
      items.map((entry) =>
        entry.localId === item.localId ? { ...entry, status: "sending", error: undefined } : entry,
      ),
    );
    void deliver(item.localId, item.text, item.files);
  }

  // El pedido de cambios del revisor (último mensaje de sistema de otra persona) se destaca.
  const highlightId =
    contract.status === "COLLECTING_DATA"
      ? [...messages]
          .reverse()
          .find((m) => m.role === "system" && m.actor !== me && /pidió cambios/i.test(m.text))?.id
      : undefined;

  return (
    <section className="chat" aria-label="Chat con el asistente">
      <div
        ref={logRef}
        className="chat__log"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        onScroll={onScroll}
      >
        {loadingOlder && <p className="muted center">Cargando mensajes anteriores…</p>}
        {hasMore && !loadingOlder && (
          <button
            type="button"
            className="btn btn--ghost chat__more"
            onClick={() => {
              prevHeight.current = logRef.current?.scrollHeight ?? 0;
              void loadOlder();
            }}
          >
            Cargar mensajes anteriores
          </button>
        )}
        {loading && <p className="muted center">Cargando conversación…</p>}
        {!loading && error != null && (
          <div className="banner banner--error" role="alert">
            <p>{describeError(error)}</p>
            <button type="button" className="btn" onClick={chat.reload}>
              Reintentar
            </button>
          </div>
        )}
        {!loading && error == null && messages.length === 0 && pending.length === 0 && (
          <p className="muted center">
            Todavía no hay mensajes. Contale al asistente los datos del contrato o adjuntá un documento.
          </p>
        )}
        {messages.map((message: ChatMessage) => (
          <MessageBubble
            key={message.id}
            message={message}
            mine={message.role === "user"}
            highlight={message.id === highlightId}
            onOpenDocument={onOpenDocument}
          />
        ))}
        {pending.map((item) => (
          <LocalBubble
            key={item.localId}
            item={item}
            onRetry={() => retry(item)}
            onDiscard={() => setPending((items) => items.filter((e) => e.localId !== item.localId))}
          />
        ))}
        {sending && (
          <p className="muted assistant-typing" role="status" aria-live="polite">
            El asistente está leyendo…
          </p>
        )}
      </div>
      <Composer
        disabledReason={disabledReasonFor(contract)}
        cooldown={cooldown}
        sending={sending}
        assistantDown={assistantDown}
        onSend={onSend}
      />
    </section>
  );
}
