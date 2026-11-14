import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useContract, useReview } from "../../api/hooks";
import type { Contract, ReviewDecision } from "../../api/types";
import { QueryState } from "../../components/Feedback";
import StatusBadge from "../../components/StatusBadge";
import { describeError, isStateConflict } from "../../lib/errors";
import { can } from "../../lib/labels";
import { FieldsList, Progress } from "../contracts/DataPanel";
import { draftPath } from "../documents/DraftDialog";
import FinalDocuments from "../documents/FinalDocuments";
import PdfFrame from "../documents/PdfFrame";
import AuditTimeline from "./AuditTimeline";
import DecisionDialog from "./DecisionDialog";

export default function ReviewDetail() {
  const { id = "" } = useParams();
  const query = useContract(id);
  return (
    <QueryState
      error={query.error}
      isLoading={query.isLoading}
      onRetry={() => void query.refetch()}
      notFound={{ backTo: "/revision", backLabel: "Volver a la bandeja" }}
    >
      {query.data && <Detail contract={query.data} reload={() => void query.refetch()} />}
    </QueryState>
  );
}

function Detail({ contract, reload }: { contract: Contract; reload: () => void }) {
  const navigate = useNavigate();
  const review = useReview(contract.id);
  const [decision, setDecision] = useState<ReviewDecision | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function onConfirm(comment: string | null) {
    if (!decision) return;
    try {
      await review.mutateAsync({ decision, comment });
    } catch (err) {
      if (isStateConflict(err)) reload();
      return;
    }
    const chosen = decision;
    setDecision(null);
    if (chosen === "APPROVE") {
      setNotice("Aprobaste el contrato. Ya se puede descargar el documento final.");
    } else if (chosen === "REJECT") {
      navigate("/revision", { state: { notice: "Rechazaste el contrato." } });
    } else {
      navigate("/revision", {
        state: { notice: "Pediste cambios. El solicitante lo va a ver en su lista." },
      });
    }
  }

  return (
    <div className="detail">
      <div className="pagehead">
        <div>
          <Link to="/revision" className="backlink">
            Bandeja de revisión
          </Link>
          <h1>
            Revisión <StatusBadge status={contract.status} label={contract.status_label} />
          </h1>
          <p className="muted">Solicitante: {contract.created_by ?? "—"}</p>
        </div>
        {can(contract.allowed_actions, "review") && (
          <div className="actions actions--row">
            <button type="button" className="btn btn--primary" onClick={() => setDecision("APPROVE")}>
              Aprobar
            </button>
            <button type="button" className="btn" onClick={() => setDecision("REQUEST_CHANGES")}>
              Pedir cambios
            </button>
            <button type="button" className="btn btn--danger" onClick={() => setDecision("REJECT")}>
              Rechazar
            </button>
          </div>
        )}
      </div>

      {notice && (
        <p className="banner banner--ok" role="status">
          {notice}
        </p>
      )}
      {contract.issues.length > 0 && (
        <section className="banner banner--error" role="alert">
          <h3>Hay datos que se contradicen</h3>
          <ul>
            {contract.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </section>
      )}

      <div className="review-grid">
        <section className="card" aria-label="Datos del contrato">
          <h2>Datos</h2>
          <Progress contract={contract} />
          <FieldsList contract={contract} />
        </section>

        <section className="card" aria-label="Documento">
          <h2>{contract.status === "APPROVED" ? "Documento final" : "Borrador"}</h2>
          {can(contract.allowed_actions, "get_final_document") ? (
            <FinalDocuments contract={contract} />
          ) : can(contract.allowed_actions, "get_draft") ? (
            <PdfFrame
              path={draftPath(contract.id)}
              filename="borrador.pdf"
              notice="Borrador: no está aprobado ni formalizado."
            />
          ) : (
            <p className="muted">No hay un documento disponible para este estado.</p>
          )}
        </section>

        <section className="card" aria-label="Historial">
          <h2>Historial</h2>
          <AuditTimeline contractId={contract.id} />
        </section>
      </div>

      {decision && (
        <DecisionDialog
          decision={decision}
          busy={review.isPending}
          error={review.error}
          onCancel={() => {
            review.reset();
            setDecision(null);
          }}
          onConfirm={(comment) => void onConfirm(comment)}
        />
      )}
      {review.error != null && !decision && (
        <p className="banner banner--error" role="alert">
          {describeError(review.error)}
        </p>
      )}
    </div>
  );
}
