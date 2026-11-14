import Dialog from "../../components/Dialog";
import PdfFrame from "./PdfFrame";

export const draftPath = (contractId: string): string =>
  `/contracts/${contractId}/document?version=draft&format=pdf`;

export default function DraftDialog({ path, onClose }: { path: string; onClose: () => void }) {
  return (
    <Dialog title="Borrador del contrato" onClose={onClose} wide>
      <PdfFrame
        path={path}
        filename="borrador.pdf"
        notice="Borrador: no está aprobado ni formalizado."
      />
    </Dialog>
  );
}
