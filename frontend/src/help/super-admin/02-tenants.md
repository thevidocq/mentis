# Tenants

Each customer is a tenant with its own documentation, settings and admins. One special tenant, the **General Knowledge Base**, holds general knowledge that applies to every customer.

## Onboard a customer

1. Open **Tenants** and select **Onboard tenant**.
2. Enter the customer name. The short identifier (slug) is created automatically.
3. Leave the status on **onboarding** while you set it up; switch it to **active** when ready.
4. Invite the customer's tenant admin from **Users**.

## Statuses

- **active**: in use
- **onboarding**: being set up
- **disabled**: kept but not in use; it disappears from the chat's `@` list and its existing chats become read-only

## Edit

Use the pencil icon to rename a tenant or change its status.

## LLM

Use the brain icon to choose the AI model that answers for this customer and its fallback (see **AI providers**). The tenant admin can do the same from **LLM**, unless you untick **Tenant admins can choose the LLM of this customer** in the same window: then they only see the model in use.

The same window chooses the customer's **Integration lookups**: *Standard* (default, every model) or *Function calling* (the model follows the thread from one lookup to the next; needs a model with function calling). Tenant admins change it themselves only when the customer uses its own LLM chosen by them. The two modes are explained in the tenant admin's help, *Customer settings*.

## Delete

Use the trash icon and type the exact tenant name to confirm. This removes the tenant's users, pending invitations, documents, vectors and every chat about it (also analysts' chats). Integrations will be removed too once available. Logs are kept according to retention.

## The General Knowledge Base

The **General Knowledge Base** is created at setup and cannot be deleted or disabled. It holds **general knowledge only**: how to handle a type of threat, playbooks, best practices — never customer names, contacts or systems, which belong to the customer's own documents. Every tenant admin and analyst reads it in the chat; only tenant admins with **Can manage the General Knowledge Base** upload and approve its documents, and every new version needs approval. Every customer's answers include it unless the customer turns it off in its settings, or the analyst turns it off for one chat; on conflicts, the customer's own procedure wins.

