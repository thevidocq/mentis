# Integrations

Mentis reads customers' ticketing, EDR and identity tools, **read only**, so analysts get live tickets, devices, alerts and users in their answers (`#` in the chat).

## Enable the types

**Integrations** in the left menu lists the integration types installed with this release:

- Ticketing: **ServiceNow**, **Jira** (Cloud and Data Center).
- EDR: **CrowdStrike Falcon**, **Microsoft Defender for Endpoint**, **Trend Vision One**.
- Identity: **Microsoft Entra ID**.

Click **Enable** on the ones tenant admins may use. Turning a type off stops every customer integration of that type at once (configurations are kept). The number on the right says how many customer integrations use it.

You do not see the customers' addresses or credentials: tenant admins configure them for their customers (see their Help, *Integrations*). The General Knowledge Base has no integrations.

## What Mentis enforces

Whatever a plugin does, the core:

- sends only read requests: GET, and POST only to the addresses a plugin declares as reads (sign-in tokens, alert queries); PUT, PATCH and DELETE never leave Mentis;
- sends requests, and the stored credentials, only to the addresses of that integration (redirects are not followed);
- limits each lookup in time and size, and each question to a few lookups;
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
