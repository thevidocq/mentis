# Getting started

The super-admin runs the platform: customers (tenants), users, email and service health.

## First steps after installation

1. **Email (SMTP)**: configure the mail server and send a test email, so invitations are delivered automatically.
2. **Tenants**: onboard each customer.
3. **Users**: invite a tenant admin for each customer, and the analysts.
4. **AI providers**: add at least one LLM (for example Claude Haiku) and test it. Without it the chat cannot answer.
5. **General documentation**: upload the documents that apply to every customer.
6. **Service status**: check that everything is operational, including the ingestion worker.
7. **Retention** and **Logs → Syslog forwarding**: set how long data is kept and, if you have a SIEM, forward the events.
8. On the server, schedule `./backup.sh` (see **Backup and configuration**).

## The three roles

| Role | Scope | What they do |
| --- | --- | --- |
| Super-admin | Whole platform | Tenants, users, platform settings; can also use the chat |
| Tenant admin | One customer | Documents, settings, LLM and admins of that customer; chat on it to test answers |
| Analyst | All customers | Chat consultation (read-only) |

> Keep at least two super-admins, so a lost phone never locks you out of the platform.
