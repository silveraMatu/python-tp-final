import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { describeError, isNotFound } from "../lib/errors";

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton__line" />
      ))}
    </div>
  );
}

export function LoadingBlock({ label = "Cargando…" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <Skeleton />
    </div>
  );
}

export function ErrorBlock({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div className="banner banner--error" role="alert">
      <p>{describeError(error)}</p>
      {onRetry && (
        <button className="btn" type="button" onClick={onRetry}>
          Reintentar
        </button>
      )}
    </div>
  );
}

export function NotFoundBlock({ backTo, backLabel }: { backTo: string; backLabel: string }) {
  return (
    <section className="card center" role="alert">
      <h1>Contrato no encontrado</h1>
      <p className="muted">No existe o no tenés acceso a él.</p>
      <Link className="btn" to={backTo}>
        {backLabel}
      </Link>
    </section>
  );
}

export function QueryState({
  error,
  isLoading,
  onRetry,
  notFound,
  children,
}: {
  error: unknown;
  isLoading: boolean;
  onRetry?: () => void;
  notFound?: { backTo: string; backLabel: string };
  children: ReactNode;
}) {
  if (isLoading) return <LoadingBlock />;
  if (error) {
    if (notFound && isNotFound(error)) return <NotFoundBlock {...notFound} />;
    return <ErrorBlock error={error} onRetry={onRetry} />;
  }
  return <>{children}</>;
}
