# Using the chat

## Ask a question

1. Click **+** (New chat), next to the search box. On a phone, the **+** at the top right does the same.
2. Choose the customer: type `@` and pick it from the list (arrows and Enter work), or click the customer button under the box. When you have several customers, **All my customers** (or **All customers**) is the default.
3. Write the question and press **Enter**. **Shift+Enter** starts a new line.

> The customer is fixed with the first message. After that, typing `@` shows the list in grey: start a new chat to ask about another customer. This keeps answers about different customers from mixing.

With a customer selected, Mentis searches that customer's documentation **plus the General Knowledge Base**: general knowledge shared by all customers (threat-handling procedures, playbooks, best practices). Everyone uses it, nothing to tick. With **All my customers** it searches every active customer assigned to you, plus the knowledge base. **General Knowledge Base** at the end of the `@` list asks the knowledge base alone.

## The Knowledge Base switch

Next to the customer, the **Knowledge Base** chip is on by default (✓). To answer only from the customer's documents, tap it and confirm **Turn off for this chat**: the chip shows crossed out and the following questions of that chat ignore the knowledge base. Tap it again to turn it back on. A new chat always starts with it on. (A customer can also turn the knowledge base off for all its chats in its Settings.)

## Read the answer

- Each answer sits in a light frame. The small line above it says **which customer** it refers to. With All customers, an answer covering several customers names each one.
- Every statement ends with a number like **1**: click it to open the **Sources** panel on the right, on that passage.
- The small **Sources** button under the answer says how many documents and sections were used; click it to open the panel. It lists each document (with its version) and the cited sections; click a section to read the exact passage. The customer is shown only when the answer mixes customers or uses the General Knowledge Base. Close it with **×** or **Esc**. On a phone it fills the screen.
- A customer's own procedure wins over the General Knowledge Base; when they differ, the answer says so.
- **Not found**: if the documentation in use does not cover the question, Mentis says so and does not guess. Ask your tenant admin to add the missing procedure.
- Under the answer: up to three **suggested questions** (one click asks them), thumbs up / thumbs down buttons to rate the answer, copy, and the name of the AI model that wrote it.

> Always check the source before acting on a contact or a time. Answers come only from the documents, but the documents can be out of date.

## Share a chat

**Share** at the top right of a chat (on a phone, the share icon next to **+**) creates a link to send to a colleague, for example at a shift change.

- The link opens the chat **read-only**, with its sources. Only colleagues **signed in to Mentis** can open it, and only if they see the chat's customer; for an *All customers* chat, every customer it searched. Answers that used a customer they do not see stay hidden, with their questions.
- Copy the link when you create it: for security Mentis does not keep it. **New link** creates another one and the old one stops working; **Revoke link** stops it. A link expires after 30 days, or when the chat is deleted.
- Whoever opens it cannot add questions or see your ratings. Creating, revoking and opening links is in the audit log.

## On a phone

The chat fills the screen. The ☰ button at the top left opens the history; **+** at the top right starts a new chat.

## History

- Past chats are in the left sidebar, grouped by day, with their customer under the title.
- **Search** finds chats by title or by words in the messages.
- Hover a chat to **rename** it (the new title is kept) or **delete** it.
- The title is written automatically from the first question.

## When something goes wrong

- **The answer could not be generated**: the AI model or the document search did not respond. Click **Retry**. If it keeps failing, tell your administrator: the technical cause is in the super-admin's Logs.
- **This customer is no longer available**: the customer was disabled, deleted or removed from your account. Start a new chat.
- **This answer is hidden**: the answer used the documentation of a customer that is no longer assigned to you. Your question stays; the answer, its sources and suggestions do not.
- The `#` **Integrations** button (live data from ticketing, EDR and SIEM) is not available yet.
