import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Tenant } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { DocumentsPage } from "./DocumentsPage";
import { PreviewPage } from "./PreviewPage";

function useGeneralId(): string | null {
  const [id, setId] = useState<string | null>(null);
  useEffect(() => {
    api<Tenant[]>("/tenants").then((ts) => setId(ts.find((t) => t.is_global)?.id ?? null)).catch(() => setId(null));
  }, []);
  return id;
}

export function GeneralDocuments() {
  const id = useGeneralId();
  return id ? <DocumentsPage tenantId={id} title="General documentation" previewBase="/admin/general/preview" /> : null;
}

export function GeneralPreview() {
  const id = useGeneralId();
  return id ? <PreviewPage tenantId={id} backTo="/admin/general" /> : null;
}

export function TenantDocuments() {
  const { user } = useAuth();
  return user?.tenant_id ? <DocumentsPage tenantId={user.tenant_id} title="Documents" previewBase="/tenant/documents/preview" /> : null;
}

export function TenantPreview() {
  const { user } = useAuth();
  return user?.tenant_id ? <PreviewPage tenantId={user.tenant_id} backTo="/tenant/documents" /> : null;
}
