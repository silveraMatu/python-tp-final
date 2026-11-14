import { useTemplates } from "../../api/hooks";
import { QueryState } from "../../components/Feedback";
import { fieldLabel } from "../../lib/labels";

export default function TemplatesPage() {
  const { data, error, isLoading, refetch } = useTemplates();
  return (
    <section>
      <h1>Tipos de contrato</h1>
      <p className="muted">
        Hoy solo está disponible el contrato por tiempo indeterminado. Las demás modalidades todavía
        no tienen una plantilla aprobada.
      </p>
      <QueryState error={error} isLoading={isLoading} onRetry={() => void refetch()}>
        <ul className="cards">
          {(data ?? []).map((template) => (
            <li key={template.modality} className="card">
              <div className="card__row">
                <strong>{template.label}</strong>
                <span className={`badge ${template.available ? "badge--APPROVED" : "badge--INITIAL"}`}>
                  {template.available ? "Disponible" : "Todavía no disponible"}
                </span>
              </div>
              {template.available && (
                <details>
                  <summary>Datos que se piden ({template.required_fields.length})</summary>
                  <ul>
                    {template.required_fields.map((path) => (
                      <li key={path}>{fieldLabel(path)}</li>
                    ))}
                  </ul>
                </details>
              )}
            </li>
          ))}
        </ul>
      </QueryState>
    </section>
  );
}
