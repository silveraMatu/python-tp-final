import { fetchBlob } from "../api/client";

// Cache en memoria de los adjuntos (su contenido no cambia nunca: `attachment.id` es único).
const cache = new Map<string, Promise<string>>();

export function attachmentBlobUrl(id: string, path: string): Promise<string> {
  let entry = cache.get(id);
  if (!entry) {
    entry = fetchBlob(path).then(({ blob }) => URL.createObjectURL(blob));
    entry.catch(() => cache.delete(id)); // permite reintentar si falló
    cache.set(id, entry);
  }
  return entry;
}

/** Al salir (o ante un 401) se revocan todas las URLs `blob:`. */
export function clearBlobCache(): void {
  for (const entry of cache.values()) {
    entry.then((url) => URL.revokeObjectURL(url)).catch(() => undefined);
  }
  cache.clear();
}
