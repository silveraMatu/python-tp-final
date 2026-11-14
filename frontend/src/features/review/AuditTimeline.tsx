import { useAudit } from "../../api/hooks";
import { QueryState } from "../../components/Feedback";
import { formatDateTime } from "../../lib/format";
import { AUDIT_DETAIL_VISIBLE, AUDIT_TEXT, STATUS_TEXT } from "../../lib/labels";

/** Línea de tiempo de la auditoría. El `detail` solo se muestra en las decisiones del revisor. */
export default function AuditTimeline({ contractId }: { contractId: string }) {
  const { data, error, isLoading, refetch } = useAudit(contractId);
  return (
    <QueryState error={error} isLoading={isLoading} onRetry={() => void refetch()}>
      {data && data.length === 0 && <p className="muted">Sin movimientos.</p>}
      <ol className="timeline">
        {(data ?? []).map((entry, index) => (
          <li key={`${entry.timestamp}-${index}`} className="timeline__item">
            <div>
              <strong>{AUDIT_TEXT[entry.action] ?? "Movimiento registrado"}</strong>
              <span className="muted">
                {" "}
                · {entry.actor} · {STATUS_TEXT[entry.status]}
              </span>
            </div>
            <time className="muted" dateTime={entry.timestamp}>
              {formatDateTime(entry.timestamp)}
            </time>
            {AUDIT_DETAIL_VISIBLE.has(entry.action) && entry.detail && (
              <p className="timeline__comment">«{entry.detail}»</p>
            )}
          </li>
        ))}
      </ol>
    </QueryState>
  );
}
