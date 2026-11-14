import type { ContractStatus } from "../api/types";
import { STATUS_TEXT } from "../lib/labels";

/** El estado se comunica con texto y color (el punto lo dibuja el CSS). */
export default function StatusBadge({ status, label }: { status: ContractStatus; label?: string }) {
  return (
    <span className={`badge badge--${status}`}>
      {label ?? STATUS_TEXT[status]}
    </span>
  );
}
