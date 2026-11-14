import { useState } from "react";
import { ApiError, fetchBlob } from "../../api/client";
import type { Contract } from "../../api/types";
import { describeError } from "../../lib/errors";
import { can } from "../../lib/labels";
import VerificationCard from "./VerificationCard";
import { triggerDownload } from "./PdfFrame";

/** Documento final (solo `APPROVED`): descarga de PDF y Word + verificación de integridad. */
export default function FinalDocuments({ contract }: { contract: Contract }) {
  const [busy, setBusy] = useState<"pdf" | "docx" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [code, setCode] = useState<string | null>(null);

  async function download(format: "pdf" | "docx") {
    setBusy(format);
    setError(null);
    try {
      const { blob, code: verificationCode, name } = await fetchBlob(
        `/contracts/${contract.id}/document?version=final&format=${format}`,
      );
      setCode(verificationCode);
      const url = URL.createObjectURL(blob);
      triggerDownload(url, name ?? `contrato.${format}`);
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  }

  const integrity = error instanceof ApiError && error.code === "export_integrity_error";
  return (
    <div className="stack">
      {can(contract.allowed_actions, "get_final_document") && (
        <section className="card" aria-label="Documento final">
          <h3>Documento final</h3>
          <div className="pdf__actions">
            <button type="button" className="btn btn--primary" disabled={busy !== null || integrity} onClick={() => void download("pdf")}>
              {busy === "pdf" ? "Preparando…" : "Descargar PDF"}
            </button>
            <button type="button" className="btn" disabled={busy !== null || integrity} onClick={() => void download("docx")}>
              {busy === "docx" ? "Preparando…" : "Descargar Word (.docx)"}
            </button>
          </div>
          {code && (
            <p>
              Código de verificación: <code>{code}</code>
            </p>
          )}
          {busy && <p className="muted">La primera generación puede tardar unos segundos…</p>}
          {error != null && (
            <p className={`banner ${integrity ? "banner--critical" : "banner--error"}`} role="alert">
              {describeError(error)}
            </p>
          )}
        </section>
      )}
      {can(contract.allowed_actions, "verify_final") && <VerificationCard contractId={contract.id} />}
    </div>
  );
}
