# Getting started

The super-admin runs the platform: customers (tenants), users, email, AI providers and service health. The super-admin does not use the chat and does not manage documents: that is the work of tenant admins and analysts.

## First steps after installation

The first super-admin is created on the server with `docker compose exec api python -m app.cli create-admin`. More super-admins are invited from **Users**.

1. **Email (SMTP)**: configure the mail server and send a test email, so invitations are delivered automatically.
2. **Tenants**: onboard each customer.
3. **Users**: invite the tenant admins and the analysts, ticking the customers each one sees. Give **General** to at least one tenant admin, who will upload the documents shared by all customers.
4. **AI providers**: add at least one LLM (for example Claude Haiku) and test it. Without it the chat cannot answer.
5. **Service status**: check that everything is operational, including the ingestion worker.
6. **Retention** and **Logs → Syslog forwarding**: set how long data is kept and, if you have a SIEM, forward the events.
7. On the server, schedule `./backup.sh` (see **Backup and configuration**).

## The three roles

| Role | Scope | What they do |
| --- | --- | --- |
| Super-admin | Whole platform | Tenants, users, AI providers, platform settings. No chat, no documents |
| Tenant admin | The ticked customers, or all | Documents, settings, LLM (if allowed) and users of those customers; chat on them |
| Analyst | The ticked customers, or all | Chat consultation (read-only) |

Tenant admins and analysts see only the customers ticked on their account. **General** (the shared documentation) is ticked by default and can be removed. **All customers, including future ones** gives every customer, also those created later.

> Keep at least two super-admins, so a lost phone never locks you out of the platform.
