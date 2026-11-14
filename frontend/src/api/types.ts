import type { components } from "./schema";

// Los tipos salen de docs/openapi.json (npm run gen:api). Solo se acotan los que la API
// declara como `string` pero tienen un conjunto cerrado de valores.
type S = components["schemas"];

export type Role = "REQUESTER" | "REVIEWER";
export type ContractStatus = S["ContractStatus"];
export type ChatRole = S["ChatRole"];

export type AllowedAction =
  | "send_message"
  | "resolve_conflict"
  | "get_draft"
  | "submit_for_review"
  | "review"
  | "get_final_document"
  | "verify_final";

export type Intent =
  | "PROVIDE_DATA"
  | "RESOLVE_CONFLICT"
  | "ASK_INFO"
  | "SUBMIT_REVIEW"
  | "SHOW_STATUS"
  | "SHOW_DRAFT"
  | "APPROVE_OR_SIGN"
  | "EDIT_CLAUSES"
  | "SMALL_TALK"
  | "BLOCKED";

export type ReviewDecision = "APPROVE" | "REJECT" | "REQUEST_CHANGES";

export interface Me {
  name: string;
  role: Role;
}

export type Contract = Omit<S["ContractOut"], "allowed_actions" | "issues"> & {
  issues: string[];
  allowed_actions: AllowedAction[];
};
export type FieldValue = S["FieldValueOut"];
export type PendingConflict = S["PendingConflictOut"];
export type Attachment = S["AttachmentMeta"];
export type DocumentRef = S["DocumentRef"];
export type ChatMessage = S["ChatMessage"];
export type ChatPage = S["ChatPage"];
export type AuditEntry = S["AuditEntryOut"];
export type Verification = S["VerificationOut"];
export type Template = S["TemplateOut"];
export type KnowledgeAnswer = S["KnowledgeAnswerOut"];

export interface MessageResult {
  reply: string;
  intent: Intent;
  classification_source: string;
  contract: Contract;
  documents: DocumentRef[];
  sources: string[];
  user_message: ChatMessage;
  agent_message: ChatMessage;
}

export interface ApiErrorBody {
  error: string;
  detail: string;
}
