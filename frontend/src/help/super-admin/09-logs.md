# Logs

**Logs** is the single place for everything that happened on the platform. Only super-admins see it.

## What is recorded

- **Audit** events: who did what. Sign-ins and failed sign-ins, 2FA, users and invitations, tenants, documents and approvals, AI provider and settings changes, chat answers, exports and imports.
- **System** events: what the platform did by itself or what went wrong. Document processing, indexing failures, LLM errors, retention purges.

Chat events carry **metadata only**: customer, model, tokens, time and number of sources. Questions and answers are never written to the logs.

## Find events

- **Period**, **type** (audit or system), **level** (info, warning, error), **tenant** and **action** filters. In the action list, `auth.*` selects a whole group.
- **Search** looks in user, target, action and IP.
- Click a row to see its details.
- **Export CSV** downloads the events matching the filters (up to 100,000 rows). Exports are themselves logged.

## Forward to a SIEM (syslog)

Click **Syslog forwarding**:

1. Turn on **Forward log events** and enter the collector **host** and **port**.
2. Choose **UDP** (514), **TCP** (514) or **TCP + TLS** (6514). With TLS, keep **Verify the collector's certificate** on unless the collector uses a self-signed certificate.
3. Click **Save and send test**. With TCP and TLS a failed connection is reported; UDP gives no confirmation, so check that the collector received the event.

Format: RFC 5424, with TCP framing by octet counting (RFC 6587). Facility *log audit* for audit events and *user* for system events; severity from the level. The structured data `[mentis@32473 kind level actor tenant target ip]` is followed by the full event as JSON:

```
<110>1 2026-11-25T16:12:47.930Z mentis-host mentis - tenant.created [mentis@32473 kind="audit" level="info" actor="alex@example.com" tenant="…" target="Acme Bank" ip="10.0.0.5"] {"action":"tenant.created",…}
```

Events are sent in the background: an unreachable collector never slows Mentis down. If it stays down, events are dropped from forwarding (they are still in Logs). **Service status** shows a **Syslog forwarding** line with sent and dropped events and the last error.

## How long events are kept

See **Retention**.
