import { useRef, useState, type ChangeEvent, type DragEvent, type KeyboardEvent } from "react";
import { ACCEPT_ATTRIBUTE, MAX_MESSAGE_CHARS, checkFiles } from "../../lib/files";

const SUGGESTIONS = [
  "Ver el estado",
  "Ver borrador",
  "¿Qué dice la cláusula de confidencialidad?",
];

interface Props {
  /** Texto de por qué no se puede escribir; `null` = habilitado. */
  disabledReason: string | null;
  /** Segundos restantes de espera por límite de mensajes (429). */
  cooldown: number;
  sending: boolean;
  assistantDown: boolean;
  onSend: (text: string, files: File[]) => void;
}

export default function Composer({ disabledReason, cooldown, sending, assistantDown, onSend }: Props) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const tooLong = text.length > MAX_MESSAGE_CHARS;
  const blocked = disabledReason !== null;
  const waiting = cooldown > 0;
  const canSend =
    !blocked && !sending && !waiting && !tooLong && (text.trim().length > 0 || files.length > 0);

  function addFiles(incoming: File[]) {
    const result = checkFiles(files, incoming);
    setFiles((current) => [...current, ...result.accepted]);
    setProblems(result.errors);
  }

  function submit() {
    if (!canSend) return;
    onSend(text.trim(), files);
    setText("");
    setFiles([]);
    setProblems([]);
  }

  /** Una sugerencia se envía como mensaje normal y no toca lo que se está escribiendo. */
  function sendSuggestion(suggestion: string) {
    if (sending || waiting) return;
    onSend(suggestion, []);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (canSend) submit();
    }
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (!blocked) addFiles(Array.from(event.dataTransfer.files));
  }

  function onPick(event: ChangeEvent<HTMLInputElement>) {
    addFiles(Array.from(event.target.files ?? []));
    event.target.value = "";
  }

  if (blocked) {
    return (
      <div className="composer composer--disabled" role="status">
        <p className="muted">{disabledReason}</p>
      </div>
    );
  }

  return (
    <div
      className={`composer${dragging ? " composer--drag" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      {assistantDown && (
        <p className="banner banner--warn" role="alert">
          El asistente no está disponible por ahora; podés seguir viendo tus contratos.
        </p>
      )}
      <div className="chips" aria-label="Sugerencias">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            className="chip"
            disabled={sending || waiting}
            onClick={() => sendSuggestion(suggestion)}
          >
            {suggestion}
          </button>
        ))}
      </div>
      {files.length > 0 && (
        <ul className="filelist">
          {files.map((file, index) => (
            <li key={`${file.name}-${index}`}>
              {file.name}{" "}
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}
                aria-label={`Quitar ${file.name}`}
              >
                quitar
              </button>
            </li>
          ))}
        </ul>
      )}
      {problems.length > 0 && (
        <ul className="banner banner--error" role="alert">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}
      <div className="composer__row">
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT_ATTRIBUTE}
          hidden
          onChange={onPick}
          aria-label="Adjuntar archivos"
        />
        <button
          type="button"
          className="btn"
          onClick={() => inputRef.current?.click()}
          aria-label="Adjuntar archivos"
        >
          Adjuntar
        </button>
        <label htmlFor="composer-text" className="sr-only">
          Mensaje para el asistente
        </label>
        <textarea
          id="composer-text"
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Escribí los datos del contrato o adjuntá un documento (Enter envía, Shift+Enter nueva línea)"
          aria-invalid={tooLong}
        />
        <button
          type="button"
          className="btn btn--primary"
          disabled={!canSend}
          onClick={() => submit()}
        >
          {waiting ? `Esperá ${cooldown} s` : sending ? "Enviando…" : "Enviar"}
        </button>
      </div>
      {(text.length > MAX_MESSAGE_CHARS - 500 || tooLong) && (
        <p className={tooLong ? "banner banner--error" : "muted"} role={tooLong ? "alert" : undefined}>
          {text.length} / {MAX_MESSAGE_CHARS} caracteres
          {tooLong ? " — el mensaje es demasiado largo." : ""}
        </p>
      )}
    </div>
  );
}
