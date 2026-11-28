# Using the chat

## Ask a question

1. Click **+** (New chat), next to the search box. On a phone, the **+** at the top right does the same.
2. Choose the customer: type `@` and pick it from the list (arrows and Enter work), or click the customer button under the box. When you have several customers, **All my customers** (or **All customers**) is the default.
3. Write the question and press **Enter**. **Shift+Enter** starts a new line.

> The customer is fixed with the first message. After that, typing `@` shows the list in grey: start a new chat to ask about another customer. This keeps answers about different customers from mixing.

With a customer selected, Mentis searches that customer's documentation **plus the General Knowledge Base**: general knowledge shared by all customers (threat-handling procedures, playbooks, best practices). Everyone uses it, nothing to tick. With **All my customers** it searches every active customer assigned to you, plus the knowledge base when every one of them uses it. **General Knowledge Base** at the end of the `@` list asks the knowledge base alone.

## The Knowledge Base switch

Next to the customer, the **Knowledge Base** chip is on by default (✓). To answer only from the customer's documents, tap it and confirm **Turn off for this chat**: the chip shows crossed out and the following questions of that chat ignore the knowledge base. Tap it again to turn it back on. A new chat always starts with it on. (A customer can also turn the knowledge base off for all its chats in its Settings.)

## Live data from the customer's tools (#)

In a chat on **one customer**, Mentis can also read the customer's ticketing, EDR and identity tools (ServiceNow, Jira, CrowdStrike, Microsoft Defender, Trend Vision One, Microsoft Entra ID), if its tenant admin connected them.

1. Type `#` (or click **Integrations** under the box) and pick one or more of the customer's integrations. The chip shows what is chosen; click it again to change the choice for the next questions.
2. Ask as usual, for example *What is the status of INC0012345?*, *Open alerts on WS-042?* *Is there a procedure for the alert WB-14-20261126-00003?* or *Is mario.rossi@acme.com blocked, and where did he sign in from?*
3. Ticket numbers (INC…, SOC-123), alert ids and similar are looked up directly; for host names, IP addresses and searches the AI model decides which lookups help.

The answer cites the records like documents: their numbers open the **Sources** panel, marked *live*, with **Open in ServiceNow** (or the product) and further links, for example the device or the IP page. The record's id in the answer is a link too, and when the answer does not link a record it cites, an **Open:** line under the answer does. Only links to the records found are clickable: any other address in an answer is shown as plain text.

- Everything is **read only**: Mentis never changes a ticket, a device or an alert.
- Data is read at the moment of the question. Lookups that fail or find nothing are named in a short line in italics under the answer, for example *CrowdStrike (EU) timed out*.
- With **All my customers**, or on the General Knowledge Base alone, there are no integrations: start a chat on one customer.
- Each lookup is in the audit log (which integration and which ticket, host or alert; never the answer).

## Read the answer

- Each answer sits in a light frame. The small line above it says **which customer** it refers to. With All customers, an answer covering several customers names each one.
- Every statement ends with a number like **1**: click it to open the **Sources** panel on the right, on that passage.
- The small **Sources** button under the answer says how many documents and sections were used; click it to open the panel. It lists each document (with its version) and the cited sections; click a section to read the exact passage. The customer is shown only when the answer mixes customers or uses the General Knowledge Base. Close it with **×** or **Esc**. On a phone it fills the screen.
- A customer's own procedure wins over the General Knowledge Base; when they differ, the answer says so.
- **Not found**: if the documentation in use does not cover the question, Mentis says so and does not guess. Ask your tenant admin to add the missing procedure.
- Under the answer: up to three **suggested questions** (one click asks them), thumbs up / thumbs down buttons to rate the answer, copy, and the name of the AI model that wrote it and of the one that checked it. *Self-checked* means no separate model checks the answers: the model that wrote the answer re-read it against its sources, a weaker check.

## The answer check

A second check compares each answer with its sources. A statement that may not match is **underlined in yellow** in the answer, with a small **⚠** after its source number. Point at the ⚠ (or tap it) to see what the check found:

- **Value not in the sources** (Level 1): a contact, time, code or other value is not in the passage that statement cites (a value found only in another passage, for example a ticket, does not count); when the source leaves no doubt it shows the right value ("the source says 30 minutes").
- **Not supported by the sources** (Level 2): a model re-read the answer and the passage, with its reason.
- **No source cited** (Level 1): the statement cites no passage, so nothing could verify it.

**Open passage ›** in the box opens that passage in **Sources**. **Level 1** means values and citations, checked without a model; **Level 2** a model; **Level 1 + 2** both: say which when you report a problem.

Under the answer, one line sums it up:

- **✓ Matches the sources**: everything shown was checked (text, headings, code blocks and table rows), every statement cites a source, and every value and statement was found in the passages it cites.
- **⚠ N statements may not match the sources: check the marked ones.**
- **Unverified answer**: it cites no source at all.
- **Checking…**: the check is running (a second or two); the answer is already readable.
- **Check not available**: the check could not run, or its reply could not be read; verify the sources yourself.
- **N statements were not checked**: a very long answer has more statements than the check reads; verify those in the sources.

For some customers an answer that does not match its sources is not shown at all: you get *Not found* with "did not match the sources".

Items of a list take the citation of their heading: under "If it is a true positive [2]", each step counts as citing passage 2 and is checked against it. A code block or a table takes the citation of the line above it. Commands in code blocks and every cell of a table are checked like the text; a problem inside a code block is listed under the answer, since the code is shown exactly as written. An answer from the **General Knowledge Base** is a normal answer, not a warning: the source is shown above it. An answer that reached the AI provider's length limit ends with a note saying it was cut: ask for the rest.

> Always check the source before acting on a contact or a time. Answers come only from the documents, but the documents can be out of date.

## Share a chat

**Share** at the top right of a chat (on a phone, the share icon next to **+**) creates a link to send to a colleague, for example at a shift change.

- The link opens the chat **read-only**, with its sources. Only colleagues **signed in to Mentis** can open it, and only if they see the chat's customer; for an *All customers* chat, every customer it searched (the link closes if you no longer have any customer). It also closes when the chat's customer is disabled. Answers that used a customer they do not see stay hidden, with their questions.
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
- **This answer was removed**: a document it used was deleted (a document uploaded by mistake, for example). Your question stays; ask again to get an answer from the documents in use.
- **Integrations** is greyed out: the chat is on several customers, or the customer has no integration yet (ask your tenant admin).
