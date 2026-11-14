import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useContract, useSubmitForReview } from "../../api/hooks";
import type { Contract } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import Dialog from "../../components/Dialog";
import { QueryState } from "../../components/Feedback";
import StatusBadge from "../../components/StatusBadge";
import { describeError, isStateConflict } from "../../lib/errors";
import { can } from "../../lib/labels";
import ChatPanel from "../chat/ChatPanel";
import { useChat } from "../chat/useChat";
import DraftDialog, { draftPath } from "../documents/DraftDialog";
import FinalDocuments from "../documents/FinalDocuments";
import AuditTimeline from "../review/AuditTimeline";
import ConflictBanner from "./ConflictBanner";
import DataPanel from "./DataPanel";

const POLL_MS = 20_000;

export default function ContractDetail() {
  const { id = "" } = useParams();
  const { user } = useAuth();
  const [tab, setTab] = useState<"chat" | "datos">("chat");

  // Contrato y chat: en revisión se refrescan cada 20 s (el revisor responde por el chat).
  const [pendingReview, setPendingReview] = useState(false);
  const query = useContract(id, pendingReview ? POLL_MS : false);
  const contract = query.data;
  const chat = useChat(id);

  useEffect(() => {
    setPendingReview(contract?.status === "PENDING_HUMAN_REVIEW");
  }, [contract?.status]);

  const status = contract?.status;
  const { refreshLatest } = chat;
  useEffect(() => {
    if (status === undefined) return;
    void refreshLatest(); // el estado cambió (p. ej. el revisor decidió): traer el aviso
  }, [status, refreshLatest]);
  useEffect(() => {
    if (!pendingReview) return;
    const timer = window.setInterval(() => void refreshLatest(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [pendingReview, refreshLatest]);

  return (
    <QueryState
      error={query.error}
      isLoading={query.isLoading}
      onRetry={() => void query.refetch()}
      notFound={{ backTo: "/contratos", backLabel: "Volver a mis contratos" }}
    >
      {contract && user && (
        <Detail
          contract={contract}
          me={user.name}
          tab={tab}
          setTab={setTab}
          chat={chat}
          reload={() => void query.refetch()}
        />
      )}
    </QueryState>
  );
}

function Detail({
  contract,
  me,
  tab,
  setTab,
  chat,
  reload,
}: {
  contract: Contract;
  me: string;
  tab: "chat" | "datos";
  setTab: (tab: "chat" | "datos") => void;
  chat: ReturnType<typeof useChat>;
  reload: () => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const submit = useSubmitForReview(contract.id);
  const [actionError, setActionError] = useState<unknown>(null);

  const canSubmit = can(contract.allowed_actions, "submit_for_review");
  const blocking = contract.pending_conflicts.length > 0 || contract.issues.length > 0;

  async function onSubmit() {
    setActionError(null);
    try {
      await submit.mutateAsync();
      setConfirmSubmit(false);
      void chat.refreshLatest();
    } catch (err) {
      setActionError(err);
      setConfirmSubmit(false);
      if (isStateConflict(err)) reload();
    }
  }

  const lastReviewerNote = [...chat.messages]
    .reverse()
    .find((m) => m.role === "system" && /rechazó/i.test(m.text));

  return (
    <div className="detail">
      <div className="pagehead">
        <div>
          <Link to="/contratos" className="backlink">
            Mis contratos
          </Link>
          <h1>
            Contrato <StatusBadge status={contract.status} label={contract.status_label} />
          </h1>
        </div>
      </div>

      {contract.status === "PENDING_HUMAN_REVIEW" && (
        <p className="banner banner--info" role="status">
          Enviado a revisión humana. Te avisamos por acá cuando el revisor decida.
        </p>
      )}
      {contract.status === "APPROVED" && (
        <p className="banner banner--ok" role="status">
          Aprobado. Ya podés descargar el documento final.
        </p>
      )}
      {contract.status === "REJECTED" && (
        <div className="banner banner--error" role="status">
          <p>
            <strong>Rechazado.</strong> El contrato quedó cerrado.
          </p>
          {lastReviewerNote && <p className="msg__text">{lastReviewerNote.text}</p>}
        </div>
      )}
      {actionError != null && (
        <p className="banner banner--error" role="alert">
          {describeError(actionError)}
        </p>
      )}

      <ConflictBanner
        contract={contract}
        canResolve={can(contract.allowed_actions, "resolve_conflict")}
        onResolved={() => void chat.refreshLatest()}
        onStateConflict={reload}
      />

      <div className="tabs" role="tablist" aria-label="Secciones">
        <button type="button" role="tab" aria-selected={tab === "chat"} onClick={() => setTab("chat")}>
          Chat
        </button>
        <button type="button" role="tab" aria-selected={tab === "datos"} onClick={() => setTab("datos")}>
          Datos
        </button>
      </div>

      <div className="panels">
        <div className="panel" data-active={tab === "chat"}>
          <ChatPanel
            contract={contract}
            chat={chat}
            me={me}
            onOpenDocument={setDraft}
            onContractChanged={reload}
          />
        </div>
        <div className="panel" data-active={tab === "datos"}>
          <DataPanel contract={contract}>
            <div className="actions">
              {can(contract.allowed_actions, "get_draft") && (
                <button type="button" className="btn" onClick={() => setDraft(draftPath(contract.id))}>
                  Ver borrador
                </button>
              )}
              {canSubmit && (
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={blocking || !contract.is_complete}
                  onClick={() => setConfirmSubmit(true)}
                >
                  Enviar a revisión
                </button>
              )}
              {canSubmit && blocking && (
                <p className="muted">Resolvé los datos pendientes antes de enviar a revisión.</p>
              )}
              <button type="button" className="btn btn--ghost" onClick={() => setShowHistory(true)}>
                Historial
              </button>
            </div>
            {contract.status === "APPROVED" && <FinalDocuments contract={contract} />}
          </DataPanel>
        </div>
      </div>

      {draft && <DraftDialog path={draft} onClose={() => setDraft(null)} />}
      {showHistory && (
        <Dialog title="Historial del contrato" onClose={() => setShowHistory(false)} wide>
          <AuditTimeline contractId={contract.id} />
        </Dialog>
      )}
      {confirmSubmit && (
        <Dialog title="Enviar a revisión humana" onClose={() => setConfirmSubmit(false)} busy={submit.isPending}>
          <p>
            ¿Enviar a revisión humana? Después no vas a poder editar los datos hasta que el revisor
            responda.
          </p>
          <div className="dialog__actions">
            <button type="button" className="btn" onClick={() => setConfirmSubmit(false)} disabled={submit.isPending}>
              Cancelar
            </button>
            <button type="button" className="btn btn--primary" onClick={() => void onSubmit()} disabled={submit.isPending}>
              {submit.isPending ? "Enviando…" : "Enviar a revisión"}
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
