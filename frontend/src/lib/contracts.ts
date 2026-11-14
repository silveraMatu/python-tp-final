import type { Contract } from "../api/types";
import { TOTAL_FIELDS } from "./labels";

export function employeeName(contract: Contract): string | null {
  const get = (path: string) => contract.fields.find((f) => f.field_name === path)?.value;
  const name = [get("employee.nombre"), get("employee.apellido")].filter(Boolean).join(" ");
  return name || null;
}

export function loadedCount(contract: Contract): number {
  return Math.max(0, TOTAL_FIELDS - contract.missing_fields.length);
}
