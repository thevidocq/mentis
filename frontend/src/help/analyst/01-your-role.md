# Your role as analyst

You consult Mentis to find what each customer's procedures say: escalations, contacts, SLAs, runbooks. Mentis only reads; it never changes anything in customer systems.

## How the chat will work

The chat is the next part being built. This is how it will behave:

- **`@` customer**: type `@` to pick the customer. **All customers** is the default. The first message locks the chat to that choice; to switch customer, start a new chat.
- **`#` integrations**: type `#` to add live data from the customer's tools (ticketing, EDR, SIEM) to a single question. You can pick several.
- **Sources**: every answer says which customer it refers to and cites its sources, such as document, version and page, or the integration and the time of reading.
- **Not found**: if the documentation does not cover your question, Mentis says so instead of guessing.
- **Follow-ups**: 2–3 suggested questions under each answer, one click away.
- **History**: past chats in the left sidebar, searchable, with rename and delete.
