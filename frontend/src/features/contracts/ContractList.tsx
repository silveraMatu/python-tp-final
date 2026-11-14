import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useContracts, useCreateContract } from "../../api/hooks";
import type { ContractStatus } from "../../api/types";
import { QueryState } from "../../components/Feedback";
import StatusBadge from "../../components/StatusBadge";
import { describeError } from "../../lib/errors";
import { employeeName, loadedCount } from "../../lib/contracts";
import { STATUS_FILTERS, TOTAL_FIELDS } from "../../lib/labels";

export default function ContractList() {
  const [filter, setFilter] = useState<ContractStatus | "">("");
  const { data, error, isLoading, refetch } = useContracts(filter);
  const create = useCreateContract();
  const navigate = useNavigate();

  async function onCreate() {
    try {
      const contract = await create.mutateAsync();
      navigate(`/contratos/${contract.id}`);
    } catch {
      /* el error se muestra debajo */
    }
  }

  return (
    <section>
      <div className="pagehead">
        <h1>Mis contratos</h1>
        <button type="button" className="btn btn--primary" onClick={() => void onCreate()} disabled={create.isPending}>
          {create.isPending ? "Creando…" : "Nuevo contrato"}
        </button>
      </div>
      {create.error != null && (
        <p className="banner banner--error" role="alert">
          {describeError(create.error)}
        </p>
      )}
      <div className="filter">
        <label htmlFor="status-filter">Estado</label>
        <select id="status-filter" value={filter} onChange={(e) => setFilter(e.target.value as ContractStatus | "")}>
          {STATUS_FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
      </div>
      <QueryState error={error} isLoading={isLoading} onRetry={() => void refetch()}>
        {data && data.length === 0 ? (
          <div className="card center">
            <p>{filter ? "No hay contratos con ese estado." : "Todavía no creaste contratos."}</p>
            {!filter && (
              <button type="button" className="btn btn--primary" onClick={() => void onCreate()}>
                Nuevo contrato
              </button>
            )}
          </div>
        ) : (
          <ul className="cards">
            {(data ?? []).map((contract) => {
              const name = employeeName(contract);
              return (
                <li key={contract.id}>
                  <Link className="card card--link" data-status={contract.status} to={`/contratos/${contract.id}`}>
                    <div className="card__row">
                      <strong>{name ?? "Sin datos todavía"}</strong>
                      <StatusBadge status={contract.status} label={contract.status_label} />
                    </div>
                    <div className="card__row muted">
                      <span>
                        {loadedCount(contract)}/{TOTAL_FIELDS} datos
                      </span>
                      {contract.pending_conflicts.length > 0 && (
                        <span className="flag">Requiere tu confirmación</span>
                      )}
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </QueryState>
    </section>
  );
}
