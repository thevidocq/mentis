# Integrations

**Integrations** in the left menu connects your customer's ticketing, EDR and identity tools. In a chat on this customer, analysts choose them with `#`: Mentis reads tickets, devices, alerts and users at the moment of the question and answers with a link to each record.

Integrations are **read only**: Mentis never creates, changes or closes anything in these systems. Use an account (or API client) with read permissions only.

## Add an integration

1. Click **Add integration** and choose the type. Only the types enabled by the super-admin are listed.
2. Give it a **name**: analysts see it after `#` (for example *ServiceNow production*).
3. Fill in the address and the credentials (see **Minimum requirements** below), then **Add**.
4. Click **Test**: Mentis signs in and reads one item. Then **Try a lookup**: read a real ticket, host or alert to check permissions and fields.

Credentials are stored encrypted and never shown again: leave a credential empty when editing to keep it. They are sent only to the address they were saved for; if you change the address, enter the credentials again.

## What analysts get

| Type | Lookups |
| --- | --- |
| **ServiceNow** | Ticket by number (INC, SIR, PRB, CHG, RITM, SCTASK), search, open tickets of a host |
| **Jira** | Issue by key (SOC-123), search, open issues that mention a host |
| **CrowdStrike** | Host details and containment, alerts of a host, alert by id, open alerts |
| **Microsoft Defender** | Device with IP links, alerts of a device, alert by id with evidence, open alerts, IP address statistics |
| **Microsoft Entra ID** | User (enabled or blocked, MFA methods, risk, last sign-in), last sign-ins of a user, users at risk |
| **Trend Vision One** | Endpoint, Workbench alerts of an endpoint, alert by id (WB-…), open alerts |

## Minimum requirements

Create the credentials as described in each product's own documentation. Mentis needs only what is listed here: **read permissions, never write**. Use a dedicated account or API client for Mentis, so its access can be reviewed and revoked on its own. Mentis must reach the listed address over HTTPS from its server: allow it in firewalls and IP allow lists.

### ServiceNow

- **Credentials**, one of: a user and password; an OAuth client with the *client credentials* grant; a REST API key.
- **Permissions**: read on the tables used: `incident` (and `sn_si_incident`, `problem`, `change_request`, `sc_req_item`, `sc_task` for those ticket numbers), plus `cmdb_ci` for *open tickets of a host*. Web service (REST) access. No write role.
- **Address**: the instance, e.g. `https://acme.service-now.com`.

### Jira

- **Credentials**: Cloud, the e-mail of an account and an API token of that account. Data Center, a personal access token.
- **Permissions**: *Browse projects* on the projects Mentis may read (list them in **Projects** to restrict lookups to them). No other permission.
- **Address**: the site, e.g. `https://acme.atlassian.net` or the Data Center URL.

### CrowdStrike Falcon

- **Credentials**: an API client (client ID and secret) in the customer's cloud (US-1, US-2, EU-1, US-GOV-1).
- **Permissions (scopes)**: **Hosts: Read**, **Alerts: Read**. Nothing else.
- **MSSP (Flight Control)**: an API client of the parent CID with access to the customer, plus the customer's **child CID**.
- **Address**: the API of that cloud, e.g. `https://api.eu-1.crowdstrike.com`.

### Microsoft Defender for Endpoint

- **Credentials**: an app registration in the customer's Entra ID with a client secret: tenant ID, client ID, secret.
- **Permissions**: application permissions of the Defender for Endpoint API (*WindowsDefenderATP*): **Machine.Read.All**, **Alert.Read.All**, **Ip.Read.All**, with admin consent.
- **Address**: `https://login.microsoftonline.com` and the API of the chosen region (e.g. `https://api-eu.securitycenter.microsoft.com`).

### Microsoft Entra ID

- **Credentials**: an app registration with a client secret: tenant ID, client ID, secret (it can be the same app as Defender, with both sets of permissions).
- **Permissions**: Microsoft Graph application permissions, with admin consent: **User.Read.All** (users), **AuditLog.Read.All** (sign-ins, last sign-in), **UserAuthenticationMethod.Read.All** (MFA methods), **IdentityRiskyUser.Read.All** (risk). A missing one only leaves its part out.
- **Licence**: sign-ins and last sign-in need Entra ID P1; risk needs P2. Without them, those parts are left out.
- **Address**: `https://login.microsoftonline.com` and `https://graph.microsoft.com`.

### Trend Vision One

- **Credentials**: an API key, in the customer's region.
- **Permissions**: a role with view-only access to **Endpoint Inventory** and **Workbench**. No response actions.
- **Address**: the API of the region, e.g. `https://api.eu.xdr.trendmicro.com`.

## Field mapping

ServiceNow and Jira read the usual fields (state, priority, assignment group, assignee, configuration item, description and the latest notes). **Extra fields** adds your own, comma separated: for example `u_customer_ref` in ServiceNow or `customfield_10010` in Jira. Check them with **Try a lookup**.

## Turn off or delete

**Turn off** keeps the configuration but analysts can no longer choose it, and chats that had it chosen stop using it. **Delete** (trash icon) also deletes the stored credentials. Every change, test and lookup is in the audit log.

## When the test fails

- *invalid credentials* (401): wrong user, password, token or secret, or expired.
- *access denied* (403): the account lacks a permission listed in **Minimum requirements**, or (Microsoft) admin consent was not granted.
- *not reachable* or *timed out*: wrong address, or the system does not accept connections from the Mentis server (firewall, IP allow list).
- *Type not enabled*: the super-admin turned this type off; the integration is kept but not used.
