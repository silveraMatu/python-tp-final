import { useVerification } from "../../api/hooks";
import { describeError } from "../../lib/errors";

/** Tarjeta «Documento verificado» / «No se pudo verificar». Verifica al abrirse. */
export default function VerificationCard({ contractId }: { contractId: string }) {
  const verification = useVerification(contractId, true);
  const { data, isFetching, error, refetch } = verification;

  return (
    <section className="card" aria-live="polite" aria-label="Verificación del documento">
      <h3>Verificación del documento</h3>
      {isFetching && !data && <p className="muted">Verificando…</p>}
      {error != null && (
        <p className="banner banner--error" role="alert">
          {describeError(error)}
        </p>
      )}
      {data &&
        (data.ok ? (
          <p className="banner banner--ok" role="status">
            <strong>Documento verificado.</strong> No fue alterado desde su emisión.
            {data.verification_code && (
              <>
                {" "}
                Código: <code>{data.verification_code}</code>
              </>
            )}
          </p>
        ) : (
          <div className="banner banner--critical" role="alert">
            <p>
              <strong>No se pudo verificar el documento.</strong>
            </p>
            <ul>
              {data.problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          </div>
        ))}
      <button type="button" className="btn" onClick={() => void refetch()} disabled={isFetching}>
        {isFetching ? "Verificando…" : "Volver a verificar"}
      </button>
    </section>
  );
}
