import type { ChatMessage } from "../../api/types";
import { isSafeApiPath } from "../../api/client";
import { formatDateTime } from "../../lib/format";
import { sourceLabel } from "../../lib/labels";
import AttachmentThumb from "./AttachmentThumb";

export interface LocalMessage {
  localId: string;
  text: string;
  files: File[];
  status: "sending" | "failed";
  error?: string;
}

interface Props {
  message: ChatMessage;
  mine: boolean;
  /** Resalta el pedido de cambios del revisor. */
  highlight?: boolean;
  onOpenDocument: (path: string) => void;
}

/**
 * Todo el contenido es TEXTO PLANO: se renderiza con `{text}` (React escapa) y
 * `white-space: pre-wrap`. Nunca HTML, Markdown ni enlaces automáticos.
 */
export default function MessageBubble({ message, mine, highlight, onOpenDocument }: Props) {
  if (message.role === "system") {
    return (
      <div className={`msg msg--system${highlight ? " msg--highlight" : ""}`} role="note">
        <span aria-hidden="true">ℹ️ </span>
        <span className="msg__text">{message.text}</span>
        <time className="msg__time" dateTime={message.timestamp}>
          {formatDateTime(message.timestamp)}
        </time>
      </div>
    );
  }
  const isAgent = message.role === "agent";
  const blocked = isAgent && message.intent === "BLOCKED";
  const drafts = (message.documents ?? []).filter((doc) => isSafeApiPath(doc.url));
  const sources = message.sources ?? [];
  const attachments = message.attachments ?? [];
  return (
    <div className={`msg ${isAgent ? "msg--agent" : "msg--user"}${mine ? " msg--mine" : ""}`}>
      <div className={`bubble${blocked ? " bubble--blocked" : ""}`}>
        <div className="bubble__author">
          {isAgent ? "Asistente" : message.actor}
          {blocked && <span className="bubble__tag"> · Aviso de seguridad</span>}
        </div>
        {message.text && <p className="msg__text">{message.text}</p>}
        {attachments.length > 0 && (
          <div className="attachments">
            {attachments.map((attachment) => (
              <AttachmentThumb key={attachment.id} attachment={attachment} />
            ))}
          </div>
        )}
        {sources.length > 0 && (
          <p className="muted bubble__sources">Fuentes: {sources.map(sourceLabel).join(", ")}</p>
        )}
        {drafts.map((doc) => (
          <button
            key={doc.url}
            type="button"
            className="chip"
            onClick={() => onOpenDocument(doc.url)}
          >
            Ver borrador
          </button>
        ))}
        <time className="msg__time" dateTime={message.timestamp}>
          {formatDateTime(message.timestamp)}
        </time>
      </div>
    </div>
  );
}

export function LocalBubble({
  item,
  onRetry,
  onDiscard,
}: {
  item: LocalMessage;
  onRetry: () => void;
  onDiscard: () => void;
}) {
  return (
    <div className="msg msg--user msg--mine msg--pending">
      <div className={`bubble${item.status === "failed" ? " bubble--failed" : ""}`}>
        {item.text && <p className="msg__text">{item.text}</p>}
        {item.files.length > 0 && (
          <p className="muted">Adjuntos: {item.files.map((f) => f.name).join(", ")}</p>
        )}
        {item.status === "sending" ? (
          <p className="muted">Enviando…</p>
        ) : (
          <div role="alert">
            <p>No se pudo enviar. {item.error}</p>
            <button type="button" className="btn" onClick={onRetry}>
              Reintentar
            </button>{" "}
            <button type="button" className="btn btn--ghost" onClick={onDiscard}>
              Descartar
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
