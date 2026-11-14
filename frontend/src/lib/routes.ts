import type { Role } from "../api/types";

export function homeFor(role: Role): string {
  return role === "REVIEWER" ? "/revision" : "/contratos";
}
