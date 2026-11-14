import type { AllowedAction, ContractStatus } from "../api/types";

export const TOTAL_FIELDS = 17;

export const FIELD_LABELS: Record<string, string> = {
  "employee.nombre": "Nombre del empleado/a",
  "employee.apellido": "Apellido del empleado/a",
  "employee.dni": "DNI del empleado/a",
  "employee.cuil": "CUIL del empleado/a",
  "employee.domicilio": "Domicilio del empleado/a",
  "employee.fecha_nacimiento": "Fecha de nacimiento del empleado/a",
  "company.razon_social": "Razón social de la empresa",
  "company.cuit": "CUIT de la empresa",
  "company.domicilio_legal": "Domicilio legal de la empresa",
  "company.apoderado_nombre": "Nombre del apoderado",
  "company.apoderado_cargo": "Cargo del apoderado",
  "terms.puesto_funcion": "Puesto o función",
  "terms.fecha_inicio": "Fecha de inicio",
  "terms.modalidad": "Modalidad de contratación",
  "terms.remuneracion_bruta": "Remuneración bruta mensual",
  "terms.jornada_laboral": "Jornada laboral",
  "terms.lugar_trabajo": "Lugar de prestación de servicios",
};

export const SECTIONS: ReadonlyArray<{ prefix: string; title: string }> = [
  { prefix: "employee", title: "Empleado/a" },
  { prefix: "company", title: "Empresa" },
  { prefix: "terms", title: "Condiciones" },
];

export function fieldLabel(path: string): string {
  return FIELD_LABELS[path] ?? path;
}

export const STATUS_TEXT: Record<ContractStatus, string> = {
  INITIAL: "Nuevo (sin datos)",
  COLLECTING_DATA: "Recolectando datos",
  CONFLICT_DETECTED: "Esperando confirmación de un dato",
  PENDING_HUMAN_REVIEW: "Pendiente de revisión humana",
  APPROVED: "Aprobado",
  REJECTED: "Rechazado",
};

export const STATUS_FILTERS: ReadonlyArray<{ value: ContractStatus | ""; label: string }> = [
  { value: "", label: "Todos" },
  { value: "INITIAL", label: "Nuevos" },
  { value: "COLLECTING_DATA", label: "Recolectando datos" },
  { value: "CONFLICT_DETECTED", label: "Con dato pendiente" },
  { value: "PENDING_HUMAN_REVIEW", label: "En revisión" },
  { value: "APPROVED", label: "Aprobados" },
  { value: "REJECTED", label: "Rechazados" },
];

export function can(actions: readonly AllowedAction[] | undefined, action: AllowedAction): boolean {
  return actions?.includes(action) ?? false;
}

/** Texto de un mensaje de sistema del chat o de una fuente citada (`clausula:SEXTA`). */
export function sourceLabel(source: string): string {
  if (source.startsWith("clausula:")) {
    const ordinal = source.slice("clausula:".length);
    return `Cláusula ${ordinal.charAt(0)}${ordinal.slice(1).toLowerCase()}`;
  }
  return source;
}

export const AUDIT_TEXT: Record<string, string> = {
  created: "Contrato creado",
  extraction_applied: "Se cargaron datos",
  conflict_accepted: "Dato confirmado",
  conflict_rejected: "Dato descartado",
  submitted_for_review: "Enviado a revisión",
  approved: "Aprobado",
  rejected: "Rechazado",
  changes_requested: "El revisor pidió cambios",
  exported_draft: "Borrador generado",
  rendered_draft: "Borrador generado",
  exported_final: "Documento final emitido",
  rendered_final: "Documento final emitido",
  security_blocked: "Se bloqueó un contenido sospechoso",
};

/** Acciones cuyo `detail` es un comentario del revisor (el resto es información técnica). */
export const AUDIT_DETAIL_VISIBLE: ReadonlySet<string> = new Set([
  "approved",
  "rejected",
  "changes_requested",
]);
