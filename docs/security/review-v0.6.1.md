# Security review v0.6.1

Four parallel reviews (authentication and access, untrusted input, deployment, data exposure) of v0.6.1, by reading the code and reproducing what could be run. Fixed in 0.6.2 unless marked otherwise.

## Fixed

| Severity | Finding | Fix |
|---|---|---|
| High | A 36 KB Word file with merged cells (`gridSpan` + `vMerge`) produced 1 GB of text: the worker shared by every customer was killed, and again at each retry. | Merged values repeated only when short; 5 M characters per file; parsing in a child process with memory and CPU limits (`ingestion/isolated.py`). |
| High | Tables nested in tables were read again at each level (2^depth): 24 levels took 42 s, 30 ran past the job timeout. | Each table reads only its own rows; nesting past 5 levels is plain text. |
| Medium | Merged-cell rows were looked up again for each row (quadratic): 20,000 empty rows took 4 minutes. | One pass; 5,000 rows per table. |
| Medium | A 200 KB web page with large `colspan`/`rowspan` used about 1 GB while being converted. | Spans repeat only short text; 250,000 slots and the page budget per table. |
| Medium | A user or invitation with no customer could be listed, changed, deleted or given a reset link by the tenant admin of any customer (an empty set is inside every set). | Only super-admins and tenant admins of all customers manage them (`access.covers_person`). |
| Medium | Deleting a document (or a customer) left its passages in saved answers (**Sources** keeps whole passages) until chat retention. | The answers that used it are removed in the same commit (`services/chat_redaction.py`). |
| Medium | Upgrades never pulled newer base images, so their security fixes never arrived. | Upgrade commands use `build --pull` and `pull`. |
| Low | Hidden answers and shared links were judged on cited passages and on the owner's current customers only; titles of "All customers" chats were written from the passages and never hidden. | Each answer records the tenants it read (`searched`); the title of an "All customers" chat is the question; a link closes when its owner has no customer left or its customer is disabled. |
| Low | Invitation, reset and share tokens were written in the access logs of the API and the web container. | Masked in both logs. |
| Low | No HSTS in the documented reverse-proxy examples. | Added to the Caddy and nginx examples. |
| Low | Very large pictures in slides were decoded in full before OCR. | Skipped above 50 M pixels (header check). |

## Accepted

- **A super-admin can take over an account** (reset its 2FA, create a reset link with SMTP off, or control SMTP) and so read a customer's documents and chats. Every step is audited and the user notices; separating these duties needs a second approver, not planned. Super-admins are trusted operators.

## Planned (deployment, needs migration steps on the VPS)

- Separate PostgreSQL roles (owner for migrations, `NOSUPERUSER` for the app) and a MinIO user limited to the bucket.
- A `reencrypt-secrets` command to finish a key rotation.
- Python dependencies locked with hashes.
- Non-root, read-only containers and memory limits for the data services; RQ with a JSON serializer.
