import { Link, NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { homeFor } from "../lib/routes";

export default function Layout() {
  const { user, logout } = useAuth();
  if (!user) return null;
  const isReviewer = user.role === "REVIEWER";
  return (
    <>
      <a className="skip-link" href="#contenido">
        Saltar al contenido
      </a>
      <header className="topbar">
        <Link to={homeFor(user.role)} className="topbar__brand">
          HumanIA <span className="muted">Contratos</span>
        </Link>
        <nav aria-label="Principal" className="topbar__nav">
          {isReviewer ? (
            <NavLink to="/revision">Bandeja de revisión</NavLink>
          ) : (
            <NavLink to="/contratos">Mis contratos</NavLink>
          )}
          <NavLink to="/ayuda/tipos-de-contrato">Tipos de contrato</NavLink>
        </nav>
        <div className="topbar__user">
          <span>
            {user.name} · <strong>{isReviewer ? "Revisor" : "Solicitante"}</strong>
          </span>
          <button className="btn btn--ghost" type="button" onClick={() => logout()}>
            Salir
          </button>
        </div>
      </header>
      <main id="contenido" className="page" tabIndex={-1}>
        <Outlet />
      </main>
    </>
  );
}
