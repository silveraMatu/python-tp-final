import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useContracts } from "../../api/hooks";
import type { ContractStatus } from "../../api/types";
import { QueryState } from "../../components/Feedback";
import StatusBadge from "../../components/StatusBadge";
import { employeeName } from "../../lib/contracts";

const TABS: ReadonlyArray<{ status: ContractStatus; label: string; empty: string }> = [
  { status: "PENDING_HUMAN_REVIEW", label: "Pendientes", empty: "No hay contratos pendientes de revisión." },
  { status: "APPROVED", label: "Aprobados", empty: "Todavía no aprobaste contratos." },
  { status: "REJECTED", label: "Rechazados", empty: "No hay contratos rechazados." },
];

export default function ReviewQueue() {
  const [tab, setTab] = useState<ContractStatus>("PENDING_HUMAN_REVIEW");
  const location = useLocation();
  const notice = (location.state as { notice?: string } | null)?.notice;
  // «Pendientes» se actualiza sola cada 30 s.
  const { data, error, isLoading, isFetching, refetch } = useContracts(
    tab,
    tab === "PENDING_HUMAN_REVIEW" ? 30_000 : undefined,
  );
  const current = TABS.find((t) => t.status === tab) ?? TABS[0]!;

  return (
    <section>
      <div className="pagehead">
        <h1>Bandeja de revisión</h1>
        <button type="button" className="btn" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching ? "Actualizando…" : "Actualizar"}
        </button>
      </div>
      {notice && (
        <p className="banner banner--ok" role="status">
          {notice}
        </p>
      )}
      <div className="tabs tabs--visible" role="tablist" aria-label="Estado">
        {TABS.map((t) => (
          <button key={t.status} type="button" role="tab" aria-selected={tab === t.status} onClick={() => setTab(t.status)}>
            {t.label}
          </button>
        ))}
      </div>
      <QueryState error={error} isLoading={isLoading} onRetry={() => void refetch()}>
        {data && data.length === 0 ? (
          <p className="card center muted">{current.empty}</p>
        ) : (
          <ul className="cards" role="tabpanel">
            {(data ?? []).map((contract) => (
              <li key={contract.id}>
                <Link className="card card--link" data-status={contract.status} to={`/revision/${contract.id}`}>
                  <div className="card__row">
                    <strong>{employeeName(contract) ?? "Sin nombre de empleado"}</strong>
                    <StatusBadge status={contract.status} label={contract.status_label} />
                  </div>
                  <div className="card__row muted">
                    <span>Solicitante: {contract.created_by ?? "—"}</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </section>
  );
}
