export const MAX_FILES = 5;
export const MAX_FILE_BYTES = 15 * 1024 * 1024;
export const MAX_MESSAGE_CHARS = 4000;
export const ACCEPTED_EXTENSIONS = ["pdf", "png", "jpg", "jpeg", "webp"] as const;
export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(",");

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot + 1).toLowerCase();
}

export interface FileCheck {
  accepted: File[];
  errors: string[];
}

/** Valida en el cliente, antes de enviar: cantidad, tamaño y tipo. */
export function checkFiles(current: readonly File[], incoming: readonly File[]): FileCheck {
  const accepted: File[] = [];
  const errors: string[] = [];
  for (const file of incoming) {
    const ext = extensionOf(file.name);
    if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(ext)) {
      errors.push(`«${file.name}»: solo se admiten PDF, PNG, JPG y WEBP.`);
    } else if (file.size > MAX_FILE_BYTES) {
      errors.push(`«${file.name}»: supera el máximo de 15 MB.`);
    } else if (file.size === 0) {
      errors.push(`«${file.name}»: el archivo está vacío.`);
    } else if (current.length + accepted.length >= MAX_FILES) {
      errors.push(`Máximo ${MAX_FILES} archivos por mensaje.`);
      break;
    } else {
      accepted.push(file);
    }
  }
  return { accepted, errors };
}
