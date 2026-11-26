# Retention

**Retention** sets how long Mentis keeps:

- **Chats**: a chat is deleted when it has had no new message for the chosen period.
- **Log events**: audit and system events. LLM usage figures come from these events, so they follow the same period.
- **Old document versions**: how many older versions of each document to keep (1, 3, 5, 10 or all, the default). The version in use, the latest one and versions waiting approval are always kept. Deleted versions go with their original file, page images, text and index entries.

Choose 30, 90 or 180 days, 1 or 2 years, a custom number of days, or **Keep forever**. The default is 1 year for both.

The worker deletes older data **once a day**. If you run several workers, only one of them does it. **Purge now** applies the saved settings immediately, after a confirmation. The page shows when the last purge ran and what it deleted. Every purge is also recorded in Logs.

Documents in use are never affected: they stay until an admin deletes them.

The daily purge also **sweeps the storage**: files and index entries left behind by a deletion while MinIO or Qdrant were unreachable are removed. The result line counts them as "leftover files or index entries cleaned".
