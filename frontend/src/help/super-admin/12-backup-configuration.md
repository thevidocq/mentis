# Backup and configuration

## Full backup (server)

The backup covers the database (users, tenants, settings, chats, logs and the text of every document), the original files, the vector index and the `.env` file. Run it on the server, from the installation folder:

```bash
cd mentis
./backup.sh
```

It writes `backups/mentis-<date>/` with:

- `postgres.sql.gz`: the database
- `minio.tar.gz`: the original documents
- `qdrant.tar.gz`: the vector index (Qdrant is paused for a few seconds)
- `env.backup`: `.env`, with the secret key that decrypts the passwords and API keys stored in the database
- `manifest.txt` and `SHA256SUMS`

> A backup contains every secret of the installation. Keep it encrypted and off the server, with the same care as the server itself.

The folder and its files are readable only by the user who ran the backup. To encrypt backups with `gpg`, set `MENTIS_BACKUP_GPG_RECIPIENT` (a public key: the server cannot read its own backups) or `MENTIS_BACKUP_PASSPHRASE_FILE` (a file with a passphrase) in `.env`: the backup then becomes `backups/mentis-<date>.tar.gpg`, and `./restore.sh backups/mentis-<date>.tar.gpg` decrypts it before restoring. Keep the passphrase or private key off the server too. Details: `INSTALL.md`, section Backup.

To run it every night at 02:30 and keep 14 days of backups:

```bash
crontab -e
30 2 * * * cd /opt/mentis && ./backup.sh >/var/log/mentis-backup.log 2>&1 && find backups -maxdepth 1 -name 'mentis-*' -mtime +14 -exec rm -rf {} +
```

Replace `/opt/mentis` with your installation folder.

## Restore

```bash
cd mentis
./restore.sh backups/mentis-<date>              # same server
./restore.sh backups/mentis-<date> --with-env   # new server: restores .env too
```

The script checks the files, asks you to type `RESTORE`, stops the application, replaces the database, documents and index, starts everything again and runs `./check.sh`. A backup from an older version is migrated automatically at start. With `--with-env`, `.env` is replaced only after you confirm, and the database password is set to the one in the restored `.env`. On a new server the script builds the images itself if they are missing.

If you restore on the same server without `--with-env` and the secret key in `.env` differs from the backup's, the script warns you: stored passwords and API keys would not decrypt.

If the vector index archive is lost or damaged, restore anyway and use **Embedding and Qdrant → Reindex everything**: the index is rebuilt from the database.

## Configuration export and import (panel)

**Backup and configuration → Export configuration** downloads a JSON file with:

- platform settings: email, embedding, retention, syslog
- AI providers
- tenants, with their status, settings and chosen LLM
- the enabled integration types, and each customer's integrations (address and options)

It **never** contains passwords, API keys, integration credentials, users, documents, chats or logs. Imported integrations are added turned off, until the tenant admin enters their credentials.

**Import…** reads such a file and first shows the changes it would make. Click **Apply** to make them. Import only adds and updates: tenants and providers that are not in the file are left alone. Afterwards, enter the API keys of any new AI provider.

Use it to copy a setup from the lab to production, or to keep the configuration under version control. It is not a backup.
