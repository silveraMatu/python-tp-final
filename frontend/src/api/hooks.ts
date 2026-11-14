import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "./client";
import type {
  AuditEntry,
  Contract,
  ContractStatus,
  KnowledgeAnswer,
  ReviewDecision,
  Template,
  Verification,
} from "./types";

export const keys = {
  contracts: (status: ContractStatus | "" = "") => ["contracts", status] as const,
  contract: (id: string) => ["contract", id] as const,
  history: (id: string) => ["history", id] as const,
  verification: (id: string) => ["verification", id] as const,
  templates: ["templates"] as const,
};

/** Reintenta una vez solo si falló la red; nunca ante respuestas del backend. */
const retryOnlyNetwork = (count: number, err: unknown): boolean =>
  count < 1 && err instanceof Error && "code" in err && (err as { code: string }).code === "network_error";

export function useContracts(status: ContractStatus | "", refetchMs?: number) {
  return useQuery({
    queryKey: keys.contracts(status),
    queryFn: () =>
      request<Contract[]>(`/contracts${status ? `?status_filter=${status}` : ""}`),
    refetchInterval: refetchMs,
    retry: retryOnlyNetwork,
  });
}

export function useContract(id: string, refetchMs?: number | false) {
  return useQuery({
    queryKey: keys.contract(id),
    queryFn: () => request<Contract>(`/contracts/${id}`),
    refetchInterval: refetchMs || false,
    retry: retryOnlyNetwork,
  });
}

export function useAudit(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.history(id),
    queryFn: () => request<AuditEntry[]>(`/contracts/${id}/history`),
    enabled,
    retry: retryOnlyNetwork,
  });
}

export function useVerification(id: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.verification(id),
    queryFn: () => request<Verification>(`/contracts/${id}/verification`),
    enabled,
    retry: false,
  });
}

export function useTemplates() {
  return useQuery({
    queryKey: keys.templates,
    queryFn: () => request<Template[]>("/templates"),
    retry: retryOnlyNetwork,
  });
}

/** Guarda el contrato que devolvió una acción: no hace falta otro GET. */
export function useSetContract() {
  const client = useQueryClient();
  return (contract: Contract) => {
    client.setQueryData(keys.contract(contract.id), contract);
    void client.invalidateQueries({ queryKey: ["contracts"] });
    void client.invalidateQueries({ queryKey: keys.history(contract.id) });
  };
}

export function useCreateContract() {
  const setContract = useSetContract();
  return useMutation({
    mutationFn: () => request<Contract>("/contracts", { method: "POST" }),
    onSuccess: setContract,
    retry: false,
  });
}

export function useResolveConflict(id: string) {
  const setContract = useSetContract();
  return useMutation({
    mutationFn: (vars: { field_name: string; accept_new: boolean }) =>
      request<Contract>(`/contracts/${id}/conflicts/resolve`, { method: "POST", json: vars }),
    onSuccess: setContract,
    retry: false,
  });
}

export function useSubmitForReview(id: string) {
  const setContract = useSetContract();
  return useMutation({
    mutationFn: () => request<Contract>(`/contracts/${id}/submit`, { method: "POST" }),
    onSuccess: setContract,
    retry: false,
  });
}

export function useReview(id: string) {
  const setContract = useSetContract();
  return useMutation({
    mutationFn: (vars: { decision: ReviewDecision; comment: string | null }) =>
      request<Contract>(`/contracts/${id}/review`, { method: "POST", json: vars }),
    onSuccess: setContract,
    retry: false,
  });
}

export function useKnowledgeQuery() {
  return useMutation({
    mutationFn: (question: string) =>
      request<KnowledgeAnswer>("/knowledge/query", { method: "POST", json: { question } }),
    retry: false,
  });
}
