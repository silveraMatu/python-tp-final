import { useEffect, useState } from "react";
import { ApiError, fetchBlob } from "../../api/client";
import { describeError } from "../../lib/errors";
import { LoadingBlock } from "../../components/Feedback";

interface State {
  url: string | null;
  code: string | null;
  name: string | null;
  error: unknown;
  loading: boolean;
}

/** Descarga un PDF protegido con la key y lo muestra desde un `blob:` (se revoca al desmontar). */
export function useProtectedDocument(path: string, reloadKey = 0): State {
  const [state, setState] = useState<State>({ url: null, code: null, name: null, error: null, loading: true });
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setState({ url: null, code: null, name: null, error: null, loading: true });
    fetchBlob(path, controller.signal)
      .then(({ blob, code, name }) => {
        objectUrl = URL.createObjectURL(blob);
        setState({ url: objectUrl, code, name, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ url: null, code: null, name: null, error, loading: false });
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path, reloadKey]);
  return state;
}

export function triggerDownload(url: string, filename: string): void {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

interface Props {
  path: string;
  /** Aviso permanente (borrador). */
  notice?: string;
  filename: string;
  missingFields?: string[];
  height?: number | string;
}

export default function PdfFrame({ path, notice, filename, height = "70vh" }: Props) {
  const [reload, setReload] = useState(0);
  const doc = useProtectedDocument(path, reload);

  if (doc.loading) {
    return (
      <div>
        <LoadingBlock label="Generando el documento…" />
        <p className="muted">Generando el documento, puede tardar unos segundos…</p>
      </div>
    );
  }

  if (doc.error || !doc.url) {
    const integrity = doc.error instanceof ApiError && doc.error.code === "export_integrity_error";
    return (
      <div className={`banner ${integrity ? "banner--critical" : "banner--error"}`} role="alert">
        <p>{describeError(doc.error)}</p>
        {!integrity && (
          <button type="button" className="btn" onClick={() => setReload((v) => v + 1)}>
            Reintentar
          </button>
        )}
      </div>
    );
  }

  const url = doc.url;
  return (
    <div className="pdf">
      {notice && (
        <p className="banner banner--warn" role="note">
          {notice}
        </p>
      )}
      {doc.code && (
        <p>
          <strong>Código de verificación:</strong> <code>{doc.code}</code>
        </p>
      )}
      <div className="pdf__actions">
        <button type="button" className="btn" onClick={() => triggerDownload(url, doc.name ?? filename)}>
          Descargar
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => window.open(url, "_blank", "noopener,noreferrer")}
        >
          Abrir en pestaña nueva
        </button>
      </div>
      <object data={url} type="application/pdf" className="pdf__frame" style={{ height }} aria-label="Vista del documento">
        <p className="muted">
          Tu navegador no puede mostrar el PDF acá. Usá «Abrir en pestaña nueva» o «Descargar».
        </p>
      </object>
    </div>
  );
}
