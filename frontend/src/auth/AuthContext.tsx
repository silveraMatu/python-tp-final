import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, loadStoredKey, onUnauthorized, request, setApiKey } from "../api/client";
import type { Me } from "../api/types";
import { clearBlobCache } from "../lib/blobs";

interface AuthState {
  user: Me | null;
  /** `true` mientras se valida una sesión guardada al recargar la página. */
  restoring: boolean;
  /** Aviso para mostrar en el ingreso (p. ej. «Tu sesión ya no es válida»). */
  notice: string | null;
  login: (key: string) => Promise<void>;
  logout: (notice?: string) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<Me | null>(null);
  const [restoring, setRestoring] = useState<boolean>(() => loadStoredKey() !== null);
  const [notice, setNotice] = useState<string | null>(null);
  const userRef = useRef<Me | null>(null);
  userRef.current = user;

  const logout = useCallback(
    (message?: string) => {
      setApiKey(null);
      setUser(null);
      setNotice(message ?? null);
      queryClient.clear();
      clearBlobCache();
    },
    [queryClient],
  );

  // Cualquier 401 en una pantalla autenticada cierra la sesión.
  useEffect(() => {
    onUnauthorized(() => {
      if (userRef.current) logout("Tu sesión ya no es válida.");
    });
    return () => onUnauthorized(null);
  }, [logout]);

  // Restaura la sesión guardada (sessionStorage) validándola con GET /me.
  useEffect(() => {
    if (!restoring) return;
    let cancelled = false;
    request<Me>("/me", { skipUnauthorizedHandler: true })
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setApiKey(null);
        if (err instanceof ApiError && err.status === 401) setNotice("Tu sesión ya no es válida.");
      })
      .finally(() => {
        if (!cancelled) setRestoring(false);
      });
    return () => {
      cancelled = true;
    };
  }, [restoring]);

  const login = useCallback(async (key: string) => {
    const me = await request<Me>("/me", { key, skipUnauthorizedHandler: true });
    setApiKey(key);
    setNotice(null);
    setUser(me);
  }, []);

  const value = useMemo(
    () => ({ user, restoring, notice, login, logout }),
    [user, restoring, notice, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth debe usarse dentro de AuthProvider");
  return ctx;
}
