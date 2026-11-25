# Users and invitations

## Invite a user

1. Open **Users** and select **Invite user**.
2. Enter name and email, then choose the role:
    - **Analyst**: chat across all customers
    - **Tenant admin**: pick the customer they administer
    - **Super-admin**: full platform access
3. Select **Send invitation**.

If SMTP is configured, the user receives an email. Otherwise Mentis shows the link: copy it and send it yourself. Links work once and expire after 72 hours. Inviting the same email again replaces the pending invitation.

## Status column

- **Active**: signed in at least once with 2FA
- **2FA not set up**: has a password but has not completed the first sign-in
- **Locked**: too many failed attempts (unlocks after 15 minutes)
- **Disabled**: cannot sign in

## Edit, disable, delete

- Pencil icon: change name, role, customer, or turn the account off. Disabling or changing the role signs the user out everywhere.
- Key icon: **reset 2FA** when a user lost their phone.
- Trash icon: delete the user.

The last active super-admin cannot be disabled, demoted or deleted, and nobody can delete themselves.

## Pending invitations

Listed under the users. Use the trash icon to revoke one.
