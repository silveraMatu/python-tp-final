import { useEffect, useRef, useState } from "react";
import type { Attachment } from "../../api/types";
import { isSafeApiPath } from "../../api/client";
import Dialog from "../../components/Dialog";
import { attachmentBlobUrl } from "../../lib/blobs";
import { formatBytes } from "../../lib/format";

/** Adjunto del chat. Se pide con la key y se muestra desde un `blob:` (carga diferida). */
export default function AttachmentThumb({ attachment }: { attachment: Attachment }) {
  const isImage = attachment.media_type.startsWith("image/");
  const safe = isSafeApiPath(attachment.url);
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isImage || !safe) return;
    const node = ref.current;
    let cancelled = false;
    const load = () => {
      attachmentBlobUrl(attachment.id, attachment.url)
        .then((value) => !cancelled && setUrl(value))
        .catch(() => !cancelled && setFailed(true));
    };
    if (!node || typeof IntersectionObserver === "undefined") {
      load();
      return () => {
        cancelled = true;
      };
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer.disconnect();
        load();
      }
    });
    observer.observe(node);
    return () => {
      cancelled = true;
      observer.disconnect();
    };
  }, [attachment.id, attachment.url, isImage, safe]);

  async function openPdf() {
    try {
      const value = await attachmentBlobUrl(attachment.id, attachment.url);
      window.open(value, "_blank", "noopener,noreferrer");
    } catch {
      setFailed(true);
    }
  }

  if (!safe) return null;

  if (!isImage) {
    return (
      <button type="button" className="attachment attachment--file" onClick={() => void openPdf()}>
        <span className="attachment__kind" aria-hidden="true">PDF</span>
        <span className="attachment__name">{attachment.filename}</span>
        <span className="muted">{formatBytes(attachment.size_bytes)}</span>
        {failed && <span role="alert"> · No se pudo abrir</span>}
      </button>
    );
  }

  return (
    <>
      <button
        ref={ref}
        type="button"
        className="attachment attachment--image"
        onClick={() => url && setOpen(true)}
        aria-label={`Ver ${attachment.filename}`}
      >
        {url ? (
          <img src={url} alt={attachment.filename} />
        ) : (
          <span className="muted">{failed ? "No se pudo cargar" : "Cargando…"}</span>
        )}
      </button>
      {open && url && (
        <Dialog title={attachment.filename} onClose={() => setOpen(false)} wide>
          <img className="attachment__full" src={url} alt={attachment.filename} />
        </Dialog>
      )}
    </>
  );
}
