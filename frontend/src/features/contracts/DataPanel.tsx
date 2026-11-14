import type { ReactNode } from "react";
import type { Contract } from "../../api/types";
import StatusBadge from "../../components/StatusBadge";
import { loadedCount } from "../../lib/contracts";
import { SECTIONS, TOTAL_FIELDS, fieldLabel } from "../../lib/labels";

export function Progress({ contract }: { contract: Contract }) {
  const loaded = loadedCount(contract);
  return (
    <div className="progress">
      <div
        className="progress__bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={TOTAL_FIELDS}
        aria-valuenow={loaded}
        aria-label="Datos cargados"
      >
        <div className="progress__fill" style={{ width: `${(loaded / TOTAL_FIELDS) * 100}%` }} />
      </div>
      <span>
        {loaded}/{TOTAL_FIELDS} datos
      </span>
    </div>
  );
}

/** Datos del contrato agrupados por sección, con lo que falta debajo en gris. */
export function FieldsList({ contract }: { contract: Contract }) {
  return (
    <>
      {SECTIONS.map(({ prefix, title }) => {
        const fields = contract.fields.filter((f) => f.field_name.startsWith(`${prefix}.`));
        const missing = contract.missing_fields.filter((p) => p.startsWith(`${prefix}.`));
        return (
          <section key={prefix} className="datasection">
            <h3>{title}</h3>
            {fields.length > 0 && (
              <dl className="fields">
                {fields.map((f) => (
                  <div key={f.field_name} className="fields__row">
                    <dt>{f.label}</dt>
                    <dd>{f.value}</dd>
                  </div>
                ))}
              </dl>
            )}
            {missing.length > 0 && (
              <ul className="missing">
                {missing.map((path) => (
                  <li key={path} className="muted">
                    Falta: {fieldLabel(path)}
                  </li>
                ))}
              </ul>
            )}
            {fields.length === 0 && missing.length === 0 && <p className="muted">Sin datos.</p>}
          </section>
        );
      })}
    </>
  );
}

export default function DataPanel({ contract, children }: { contract: Contract; children?: ReactNode }) {
  return (
    <aside className="datapanel card" aria-label="Datos del contrato">
      <div className="datapanel__head">
        <StatusBadge status={contract.status} label={contract.status_label} />
        <Progress contract={contract} />
      </div>
      <FieldsList contract={contract} />
      {children}
    </aside>
  );
}
