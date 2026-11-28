# Email (SMTP)

Mentis uses email only for invitations, for now.

## Settings

| Field | Example |
| --- | --- |
| Host | smtp.office365.com |
| Port | 587 (STARTTLS) or 465 (SSL/TLS) |
| Security | STARTTLS, SSL/TLS or None |
| Username / Password | the mailbox or relay account |
| Sender address | mentis@yourcompany.com |

The password is stored encrypted and never shown again. Leave the field empty to keep the stored one. It is only sent to the server it was saved for: when you change the server, enter the password again.

## Test

Enter a recipient under **Send a test email** and select **Send test**. If it fails, the error from the mail server is shown.

> Invitation links use the address set in `MENTIS_PUBLIC_URL` on the server. If links point to the wrong address, fix it there.
