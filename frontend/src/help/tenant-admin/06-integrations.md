# Integrations

**Integrations** in the left menu connects your customer's ticketing and EDR tools. In a chat on this customer, analysts choose them with `#`: Mentis reads tickets, devices and alerts at the moment of the question and answers with a link to each record.

Integrations are **read only**: Mentis never creates, changes or closes anything in these systems. Use an account (or API client) with read permissions only.

## Add an integration

1. Click **Add integration** and choose the type. Only the types enabled by the super-admin are listed.
2. Give it a **name**: analysts see it after `#` (for example *ServiceNow production*).
3. Fill in the address and the credentials (see below), then **Add**.
4. Click **Test**: Mentis signs in and reads one item. Then **Try a lookup**: read a real ticket, host or alert to check permissions and fields.

Credentials are stored encrypted and never shown again: leave a credential empty when editing to keep it. They are sent only to the address they were saved for; if you change the address, enter the credentials again.

## The types

| Type | What analysts get | What you need |
| --- | --- | --- |
| **ServiceNow** | Tickets by number (INC, SIR, PRB, CHG, RITM, SCTASK), search, open tickets of a host | Instance URL; a user with read access (e.g. `itil`), an OAuth client (client credentials) or an API key. *Table for searches*: `incident`, or `sn_si_incident` for Security Incident Response |
| **Jira** | Issues by key (SOC-123), search, open issues that mention a host | Site URL. Cloud: account e-mail and API token. Data Center: personal access token. *Projects* limits what Mentis reads |
| **CrowdStrike** | Host details and containment, alerts of a host, alert by id, open alerts | Cloud (US-1, US-2, EU-1, US-GOV-1), API client with **Hosts: Read** and **Alerts: Read**. Child CID for Flight Control (MSSP) |
| **Microsoft Defender** | Device details with IP links, alerts of a device, alert by id with evidence, open alerts, IP address statistics | Entra app registration with application permissions **Machine.Read.All**, **Alert.Read.All**, **Ip.Read.All** (admin consent): tenant ID, client ID, client secret, API region |
| **Trend Vision One** | Endpoint details, Workbench alerts of an endpoint, alert by id (WB-…), open alerts | Region and an API key whose role can view Endpoint Inventory and Workbench |

## Field mapping

ServiceNow and Jira read the usual fields (state, priority, assignment group, assignee, configuration item, description and the latest notes). **Extra fields** adds your own, comma separated: for example `u_customer_ref` in ServiceNow or `customfield_10010` in Jira. Check them with **Try a lookup**.

## Turn off or delete

**Turn off** keeps the configuration but analysts can no longer choose it, and chats that had it chosen stop using it. **Delete** (trash icon) also deletes the stored credentials. Every change, test and lookup is in the audit log.

## When the test fails

- *invalid credentials* (401): wrong user, password, token or secret, or expired.
- *access denied* (403): the account lacks a permission listed above.
- *not reachable* or *timed out*: wrong address, or the system does not accept connections from the Mentis server (firewall, IP allow list).
- *Type not enabled*: the super-admin turned this type off; the integration is kept but not used.
