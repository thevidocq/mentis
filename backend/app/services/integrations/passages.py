"""Integration results as numbered passages: the same path as document passages, so citations,
the Sources panel and the answer check work on live data too."""

import uuid
from dataclasses import dataclass

from app.connectors.contract import Connector, Record
from app.models import Integration, Tenant

KIND_LABEL = {"ticket": "Ticket", "device": "Device", "alert": "Alert", "indicator": "Indicator", "user": "User"}


@dataclass
class IntegrationPassage:
    tenant_id: uuid.UUID
    tenant_name: str
    integration_id: uuid.UUID
    integration_name: str
    product: str           # plugin label, e.g. "ServiceNow"
    record_kind: str
    record_id: str
    url: str | None
    text: str
    links: dict[str, str] | None = None
    is_general: bool = False
    source: str = "integration"
    score: float = 1.0
    heading: str | None = None

    # Names used by the prompt and the citations of document passages.
    @property
    def document_name(self) -> str:
        return f"{self.product} {KIND_LABEL.get(self.record_kind, self.record_kind)} {self.record_id}"

    @property
    def page_label(self) -> str:
        return f"live data, {self.integration_name}"


def record_text(r: Record) -> str:
    lines = [f"{KIND_LABEL.get(r.kind, r.kind)} {r.id}: {r.title}".strip()]
    lines += [f"{k}: {v}" for k, v in r.fields.items()]
    if r.updated:
        lines.append(f"Last updated: {r.updated}")
    if r.url:
        lines.append(f"Link: {r.url}")
    lines += [f"Link ({label}): {url}" for label, url in r.links.items()]
    if r.text:
        lines += ["", r.text]
    return "\n".join(lines)


def to_passages(tenant: Tenant, inst: Integration, c: Connector, records: list[Record]) -> list[IntegrationPassage]:
    return [IntegrationPassage(tenant_id=tenant.id, tenant_name=tenant.name, integration_id=inst.id, integration_name=inst.name,
                               product=c.manifest.label, record_kind=r.kind, record_id=r.id, url=r.url, text=record_text(r),
                               links=dict(r.links))
            for r in records]
