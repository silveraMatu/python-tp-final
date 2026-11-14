import { useState } from "react";
import type { ReviewDecision } from "../../api/types";
import Dialog from "../../components/Dialog";
import { describeError } from "../../lib/errors";

const MAX_COMMENT = 500;

const COPY: Record<ReviewDecision, { title: string; summary: string; confirm: string; required: boolean }> = {
  APPROVE: {
    title: "Aprobar contrato",
    summary: "Vas a aprobar este contrato. Quedará cerrado y se podrá emitir el documento final.",
    confirm: "Confirmar aprobación",
    required: false,
  },
  REQUEST_CHANGES: {
    title: "Pedir cambios",
    summary: "El contrato vuelve al solicitante para completar o corregir datos. Dejá un motivo claro.",
    confirm: "Confirmar pedido de cambios",
    required: true,
  },
  REJECT: {
    title: "Rechazar contrato",
    summary: "Vas a rechazar este contrato. Quedará cerrado y no se podrá modificar.",
    confirm: "Confirmar rechazo",
    required: true,
  },
};

interface Props {
  decision: ReviewDecision;
  busy: boolean;
  error: unknown;
  onCancel: () => void;
  onConfirm: (comment: string | null) => void;
}

/**
 * La decisión se confirma solo con un clic explícito en el botón de confirmación:
 * no es un formulario, así que Enter no la dispara.
 */
export default function DecisionDialog({ decision, busy, error, onCancel, onConfirm }: Props) {
  const copy = COPY[decision];
  const [comment, setComment] = useState("");
  const trimmed = comment.trim();
  const invalid = (copy.required && trimmed.length === 0) || comment.length > MAX_COMMENT;

  return (
    <Dialog title={copy.title} onClose={onCancel} busy={busy}>
      <p>{copy.summary}</p>
      <label htmlFor="decision-comment">
        Comentario {copy.required ? "(obligatorio)" : "(opcional)"}
      </label>
      <textarea
        id="decision-comment"
        rows={4}
        value={comment}
        maxLength={MAX_COMMENT + 100}
        onChange={(e) => setComment(e.target.value)}
        aria-required={copy.required}
        aria-invalid={comment.length > MAX_COMMENT}
      />
      <p className="muted">
        {comment.length} / {MAX_COMMENT}
      </p>
      {error != null && (
        <p className="banner banner--error" role="alert">
          {describeError(error)}
        </p>
      )}
      <div className="dialog__actions">
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>
          Cancelar
        </button>
        <button
          type="button"
          className={`btn ${decision === "REJECT" ? "btn--danger" : "btn--primary"}`}
          disabled={busy || invalid}
          onClick={() => onConfirm(trimmed || null)}
        >
          {busy ? "Enviando…" : copy.confirm}
        </button>
      </div>
    </Dialog>
  );
}
