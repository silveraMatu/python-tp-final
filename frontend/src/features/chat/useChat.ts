import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "../../api/client";
import type { ChatMessage, ChatPage } from "../../api/types";

const PAGE_SIZE = 50;

function merge(current: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const byId = new Map<string, ChatMessage>();
  for (const message of current) byId.set(message.id, message);
  for (const message of incoming) byId.set(message.id, message);
  return [...byId.values()].sort((a, b) => a.seq - b.seq);
}

export interface ChatHistory {
  messages: ChatMessage[];
  hasMore: boolean;
  loading: boolean;
  loadingOlder: boolean;
  error: unknown;
  /** Se incrementa cuando se anteponen mensajes (para conservar el scroll). */
  prependVersion: number;
  loadOlder: () => Promise<void>;
  /** Vuelve a pedir la última página y la mezcla con lo que ya hay. */
  refreshLatest: () => Promise<void>;
  append: (...items: ChatMessage[]) => void;
  reload: () => void;
}

/** Historial del chat: últimos mensajes, páginas anteriores hacia atrás y mezcla por `id`. */
export function useChat(contractId: string): ChatHistory {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [prependVersion, setPrependVersion] = useState(0);
  const nextBefore = useRef<number | null>(null);
  const loadingOlderRef = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const loadInitial = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await request<ChatPage>(`/contracts/${contractId}/messages?limit=${PAGE_SIZE}`);
      if (!mounted.current) return;
      setMessages(page.items);
      setHasMore(page.has_more);
      nextBefore.current = page.next_before ?? null;
    } catch (err) {
      if (mounted.current) setError(err);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [contractId]);

  useEffect(() => {
    setMessages([]);
    setHasMore(false);
    nextBefore.current = null;
    void loadInitial();
  }, [loadInitial]);

  const loadOlder = useCallback(async () => {
    if (loadingOlderRef.current || nextBefore.current === null) return;
    loadingOlderRef.current = true;
    setLoadingOlder(true);
    try {
      const page = await request<ChatPage>(
        `/contracts/${contractId}/messages?limit=${PAGE_SIZE}&before=${nextBefore.current}`,
      );
      if (!mounted.current) return;
      setMessages((current) => merge(current, page.items));
      setHasMore(page.has_more);
      nextBefore.current = page.next_before ?? null;
      setPrependVersion((v) => v + 1);
    } catch (err) {
      if (mounted.current) setError(err);
    } finally {
      loadingOlderRef.current = false;
      if (mounted.current) setLoadingOlder(false);
    }
  }, [contractId]);

  const refreshLatest = useCallback(async () => {
    try {
      const page = await request<ChatPage>(`/contracts/${contractId}/messages?limit=${PAGE_SIZE}`);
      if (mounted.current) setMessages((current) => merge(current, page.items));
    } catch {
      /* el refresco periódico no interrumpe la pantalla */
    }
  }, [contractId]);

  const append = useCallback((...items: ChatMessage[]) => {
    setMessages((current) => merge(current, items));
  }, []);

  return {
    messages,
    hasMore,
    loading,
    loadingOlder,
    error,
    prependVersion,
    loadOlder,
    refreshLatest,
    append,
    reload: () => void loadInitial(),
  };
}
