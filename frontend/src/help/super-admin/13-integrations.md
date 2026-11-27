# Integrations

Mentis reads customers' ticketing, EDR and identity tools, **read only**, so analysts get live tickets, devices, alerts and users in their answers (`#` in the chat).

## Enable the types

**Integrations** in the left menu lists the integration types installed with this release:

- Ticketing: **ServiceNow**, **Jira** (Cloud and Data Center).
- EDR: **CrowdStrike Falcon**, **Microsoft Defender for Endpoint**, **Trend Vision One**.
- Identity: **Microsoft Entra ID**.

Click **Enable** on the ones tenant admins may use. Turning a type off stops every customer integration of that type at once (configurations are kept). The number on the right says how many customer integrations use it.

You do not see the customers' addresses or credentials: tenant admins configure them for their customers (see their Help, *Integrations*). The General Knowledge Base has no integrations.

## Private network addresses

By default integrations reach only **public HTTPS addresses**. **Private network addresses** (top of the page) also allows private networks (10.x, 172.16–31.x, 192.168.x) and plain HTTP, for on-premise systems reached through a VPN from the server. Mentis' own services (database, index, storage, queue, the API itself), loopback and cloud metadata addresses (169.254.169.254) are refused either way. Turn it on only if a customer needs it: it lets tenant admins point integrations, and documents added from a link, at your private networks.

## What Mentis enforces

Whatever a plugin does, the core:

- sends only read requests: GET, and POST only to the addresses a plugin declares as reads (sign-in tokens, alert queries); PUT, PATCH and DELETE never leave Mentis;
- sends requests, and the stored credentials, only to the addresses of that integration (redirects are not followed), over HTTPS;
- resolves the address once, refuses local, metadata, internal and (unless allowed) private destinations, and connects to the checked IP, so a DNS change cannot redirect the call;
- limits each lookup in time (30 seconds in total) and size (2 MB, after decompression), each question to a few lookups, and runs at most 6 lookups at once;
- limits each user to 20 Test / Try a lookup per minute and 30 chat questions per minute;
- uses an integration only in chats on its own customer;
- treats records as data, never as instructions, and keeps only links to the records found in answers.

## Lookup mode per customer

Each customer uses **Standard** (default: lookups decided before reading any data, one model call, every model) or **Function calling** (the model reads each result and can ask for further lookups, up to 3 steps and 8 lookups). You choose it in **Tenants → LLM**; tenant admins only when the customer uses its own LLM chosen by them. A model without function calling falls back to Standard (`integration.tools_unavailable` in Logs). Changes are logged as `tenant.integration_mode`.

## Status and logs

- **Service status** has one line per active integration (its Test, category *Integrations*).
- **Logs**: `integration.called` (who, which integration, which operation and object, ok or the cause), `integration.created`, `.updated`, `.deleted`, `.tested`, `chat.integrations` (an analyst chose integrations for a chat) and `platform.integrations` (types enabled or disabled).
- **LLM usage** has a row *<model> · integration lookups* for the short call that chooses the lookups of each question (`integration.planned` in Logs).

## Configuration export

The export contains the enabled types and each customer's integrations **without credentials**. Imported integrations are added **turned off**: the tenant admin enters the credentials and turns them on. An integration whose address changes with the import loses its stored credentials.

## New plugins

Plugins live in the repository (`plugins/<name>/`) and ship with releases; they cannot be uploaded from the admin panel.
