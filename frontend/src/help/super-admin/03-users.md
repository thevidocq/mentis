# Users and invitations

## Invite a user

1. Open **Users** and select **Invite user**.
2. Enter name and email, then choose the role:
    - **Analyst**: chat on the ticked customers
    - **Tenant admin**: manages the ticked customers (documents, settings, users) and chats on them
    - **Super-admin**: platform management only (no chat, no documents)
3. For analysts and tenant admins, choose the customers:
    - tick one or more customers. **General** (the shared documentation) is ticked by default: untick it if the user must not see it. A tenant admin with General manages the General documents.
    - or tick **All customers, including future ones**: the user sees every customer, also those created later.
4. Select **Send invitation**.

If SMTP is configured, the user receives an email. Otherwise Mentis shows the link: copy it and send it yourself. Links work once and expire after 72 hours. Inviting the same email again replaces the pending invitation.

## Status column

- **Active**: signed in at least once with 2FA
- **2FA not set up**: has a password but has not completed the first sign-in
- **Locked**: too many failed attempts (unlocks after 15 minutes)
- **Disabled**: cannot sign in

## Edit, disable, delete

- Pencil icon: change name, role, customers, or turn the account off. Disabling, changing the role or the customers signs the user out everywhere. Past answers that used a customer the user no longer has are hidden in its chats.
- Envelope icon: **password reset link** for a user who forgot the password. It is emailed when SMTP works, otherwise shown to copy and send yourself; it works once for 24 hours, and the user still needs the authenticator app.
- Key icon: **reset 2FA** when a user lost their phone.
- Trash icon: delete the user.

The last active super-admin cannot be disabled, demoted or deleted, and nobody can delete themselves.

## Who manages whom

Tenant admins also invite and edit tenant admins and analysts, but only with customers they have themselves. A tenant admin with **All customers** can give all customers. Tenant admins never see or change super-admins, nor users who have customers they do not have. Everything is recorded in **Logs**.

## Users with several customers

In the tenant area a **customer selector** at the top of the menu chooses which customer the pages show. In the chat, `@` lists only the user's customers, plus **All my customers**.

When a customer is deleted, its users lose it; a tenant admin left with no customer is deleted.

## Pending invitations

Listed under the users. Use the trash icon to revoke one.
