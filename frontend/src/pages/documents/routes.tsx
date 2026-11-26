import { useCurrentTenant } from "../../auth/currentTenant";
import { DocumentsPage } from "./DocumentsPage";
import { PreviewPage } from "./PreviewPage";

export function TenantDocuments() {
  const { current } = useCurrentTenant();
  return current ? <DocumentsPage key={current.id} tenantId={current.id} title={current.is_general ? "General Knowledge Base" : "Documents"} general={!!current.is_general} scopeName={current.name} previewBase="/tenant/documents/preview" /> : null;
}

export function TenantPreview() {
  const { current } = useCurrentTenant();
  return current ? <PreviewPage key={current.id} tenantId={current.id} backTo="/tenant/documents" /> : null;
}
