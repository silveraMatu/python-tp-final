import { useEffect, useId, useRef, type ReactNode } from "react";

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

interface DialogProps {
  title: string;
  onClose: () => void;
  /** Mientras `busy` el diálogo no se cierra con Esc ni con el fondo. */
  busy?: boolean;
  wide?: boolean;
  children: ReactNode;
}

/** Diálogo modal accesible: atrapa el foco, se cierra con Esc y devuelve el foco al cerrar. */
export default function Dialog({ title, onClose, busy = false, wide = false, children }: DialogProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const busyRef = useRef(busy);
  busyRef.current = busy;

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const first = node?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? node)?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busyRef.current) {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !node) return;
      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const firstItem = items[0] as HTMLElement;
      const lastItem = items[items.length - 1] as HTMLElement;
      if (event.shiftKey && document.activeElement === firstItem) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && document.activeElement === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      previous?.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      className="overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={ref}
        className={`dialog${wide ? " dialog--wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className="dialog__header">
          <h2 id={titleId}>{title}</h2>
          <button className="btn btn--ghost" type="button" onClick={onClose} disabled={busy} >
            Cerrar
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}
