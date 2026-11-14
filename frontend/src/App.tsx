import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import LoginPage from "./auth/LoginPage";
import RequireRole from "./auth/RequireRole";
import Layout from "./components/Layout";
import ContractDetail from "./features/contracts/ContractDetail";
import ContractList from "./features/contracts/ContractList";
import TemplatesPage from "./features/help/TemplatesPage";
import ReviewDetail from "./features/review/ReviewDetail";
import ReviewQueue from "./features/review/ReviewQueue";
import { homeFor } from "./lib/routes";

function Home() {
  const { user, restoring } = useAuth();
  if (restoring) return <p className="center muted">Cargando…</p>;
  return <Navigate to={user ? homeFor(user.role) : "/ingresar"} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/ingresar" element={<LoginPage />} />
      <Route
        element={
          <RequireRole>
            <Layout />
          </RequireRole>
        }
      >
        <Route path="/contratos" element={<RequireRole role="REQUESTER"><ContractList /></RequireRole>} />
        <Route path="/contratos/:id" element={<RequireRole role="REQUESTER"><ContractDetail /></RequireRole>} />
        <Route path="/revision" element={<RequireRole role="REVIEWER"><ReviewQueue /></RequireRole>} />
        <Route path="/revision/:id" element={<RequireRole role="REVIEWER"><ReviewDetail /></RequireRole>} />
        <Route path="/ayuda/tipos-de-contrato" element={<TemplatesPage />} />
      </Route>
      <Route path="/" element={<Home />} />
      <Route path="*" element={<Home />} />
    </Routes>
  );
}
