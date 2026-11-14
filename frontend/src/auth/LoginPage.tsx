import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { homeFor } from "../lib/routes";
import { useAuth } from "./AuthContext";

export default function LoginPage() {
  const { user, login, notice } = useAuth();
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [waitUntil, setWaitUntil] = useState(0);

  if (user) return <Navigate to={homeFor(user.role)} replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!key.trim() || busy || Date.now() < waitUntil) return;
    setBusy(true);
    setError(null);
    try {
      await login(key.trim());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("La API key no es válida.");
      } else if (err instanceof ApiError && err.status === 429) {
        const seconds = err.retryAfter ?? 30;
        setWaitUntil(Date.now() + seconds * 1000);
        setError(`Demasiados intentos. Probá de nuevo en ${seconds} segundos.`);
      } else if (err instanceof ApiError && err.status === 0) {
        setError("No pudimos conectar con el servidor.");
      } else {
        setError("No se pudo ingresar. Probá de nuevo.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form className="card login__card" onSubmit={onSubmit}>
        <h1>HumanIA · Contratos laborales</h1>
        <p className="muted">Ingresá con tu API key para continuar.</p>
        {notice && (
          <p className="banner banner--warn" role="alert">
            {notice}
          </p>
        )}
        <label htmlFor="api-key">API key</label>
        <input
          id="api-key"
          type="password"
          autoComplete="off"
          autoFocus
          value={key}
          onChange={(e) => setKey(e.target.value)}
          aria-describedby={error ? "login-error" : undefined}
        />
        {error && (
          <p id="login-error" className="banner banner--error" role="alert">
            {error}
          </p>
        )}
        <button className="btn btn--primary" type="submit" disabled={busy || !key.trim()}>
          {busy ? "Ingresando…" : "Ingresar"}
        </button>
      </form>
    </main>
  );
}
