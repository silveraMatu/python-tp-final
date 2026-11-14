import { useState } from "react";
import { useResolveConflict } from "../../api/hooks";
import type { Contract } from "../../api/types";
import { describeError, isStateConflict } from "../../lib/errors";

interface Props {
  contract: Contract;
  /** Refresca el chat (la confirmación deja un mensaje de sistema) o recarga ante un 409. */
  onResolved: () => void;
  onStateConflict: () => void;
  canResolve: boolean;
}

/** Banner fijo con cada dato pendiente de confirmación y los problemas entre campos. */
export default function ConflictBanner({ contract, onResolved, onStateConflict, canResolve }: Props) {
  const resolve = useResolveConflict(contract.id);
  const [error, setError] = useState<unknown>(null);
  const [working, setWorking] = useState<string | null>(null);

  if (contract.pending_conflicts.length === 0 && contract.issues.length === 0) return null;

  async function decide(fieldName: string, acceptNew: boolean) {
    setError(null);
    setWorking(fieldName);
    try {
      await resolve.mutateAsync({ field_name: fieldName, accept_new: acceptNew });
      onResolved();
    } catch (err) {
      setError(err);
      if (isStateConflict(err)) onStateConflict();
    } finally {
      setWorking(null);
    }
  }

  return (
    <div className="stack">
      {contract.pending_conflicts.length > 0 && (
        <section className="banner banner--warn" role="alert" aria-label="Datos pendientes de confirmación">
          <h3>Hay datos pendientes de tu confirmación</h3>
          <ul className="conflicts">
            {contract.pending_conflicts.map((conflict) => (
              <li key={conflict.field_name} className="conflicts__item">
                <div>
                  <strong>{conflict.label}:</strong> <span>{conflict.value}</span>
                  {conflict.detail && <p className="muted">{conflict.detail}</p>}
                </div>
                {canResolve && (
                  <div className="conflicts__actions">
                    <button
                      type="button"
                      className="btn btn--primary"
                      disabled={working !== null}
                      onClick={() => void decide(conflict.field_name, true)}
                    >
                      Usar este valor
                    </button>
                    <button
                      type="button"
                      className="btn"
                      disabled={working !== null}
                      onClick={() => void decide(conflict.field_name, false)}
                    >
                      Descartar
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
          {error != null && <p role="alert">{describeError(error)}</p>}
        </section>
      )}
      {contract.issues.length > 0 && (
        <section className="banner banner--error" role="alert" aria-label="Inconsistencias">
          <h3>Hay datos que se contradicen</h3>
          <ul>
            {contract.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
          <p className="muted">Corregilo escribiendo el dato correcto en el chat.</p>
        </section>
      )}
    </div>
  );
}
