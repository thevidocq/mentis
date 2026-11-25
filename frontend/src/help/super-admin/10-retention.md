# Retention

**Retention** sets how long Mentis keeps:

- **Chats**: a chat is deleted when it has had no new message for the chosen period.
- **Log events**: audit and system events. LLM usage figures come from these events, so they follow the same period.

Choose 30, 90 or 180 days, 1 or 2 years, a custom number of days, or **Keep forever**. The default is 1 year for both.

The worker deletes older data **once a day**. If you run several workers, only one of them does it. **Purge now** applies the saved settings immediately, after a confirmation. The page shows when the last purge ran and what it deleted. Every purge is also recorded in Logs.

Documents are not affected: they stay until an admin deletes them.
