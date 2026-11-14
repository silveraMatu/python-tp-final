import type { ReactNode } from "react";
import { Link, Navigate } from "react-router-dom";
import type { Role } from "../api/types";
import { useAuth } from "./AuthContext";

/** Comodidad de la interfaz, no seguridad: el backend valida cada pedido. */
export default function RequireRole({ role, children }: { role?: Role; children: ReactNode }) {
  const { user, restoring } = useAuth();
  if (restoring) return <p className="center muted">Cargando…</p>;
  if (!user) return <Navigate to="/ingresar" replace />;
  if (role && user.role !== role) {
    return (
      <section className="card center" role="alert">
        <h1>No tenés acceso a esta sección</h1>
        <Link className="btn" to="/">
          Volver al inicio
        </Link>
      </section>
    );
  }
  return <>{children}</>;
}
