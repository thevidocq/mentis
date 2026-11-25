# Tenants

Each customer is a tenant with its own documentation, settings and admins. One special tenant, **General**, holds documentation that applies to every customer.

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

Use the brain icon to choose the AI model that answers for this customer and its fallback (see **AI providers**). The tenant admin can do the same from **LLM**.

## Delete

Use the trash icon and type the exact tenant name to confirm. This removes the tenant's users, pending invitations, documents, vectors and every chat about it (also analysts' chats). Integrations will be removed too once available. Logs are kept according to retention.

## The General tenant

General is created at setup. It cannot be deleted or disabled and has no tenant admins: super-admins manage its documentation. Every customer's answers include it unless that customer turns it off in its settings; on conflicts, the customer's own procedure wins.
