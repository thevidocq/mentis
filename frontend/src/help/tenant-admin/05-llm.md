# LLM and testing answers

## Choose the LLM

**LLM** in the left menu chooses which AI model writes the answers about your customer. The super-admin decides, for each customer, whether tenant admins may change it: if not, the page only shows the model in use.

- **LLM for answers**: *Platform default* uses the model chosen by the super-admin. Pick another one from the list if your customer needs it, for example an internal model (gpt-oss, Ollama) when documents must not reach a cloud provider.
- **Fallback when it fails**: used only if the first model does not respond. Leave it on *None*, or pick an internal one, if the customer's data must stay internal.

- **Model that checks the answers**: the model that re-reads each answer against its sources (level 2). By default the platform's checker, or your customer's own LLM when you chose one above, so its data stays with that provider.

The list shows the models added by the super-admin (name and model). Analysts see the model's name under each answer.

## Answer check

When an answer does not match its sources:

- **Show a warning** (recommended): the analyst sees the answer with what is not in the sources highlighted, and which level found it.
- **Hide the answer**: the answer is checked before it is shown; if it fails, it is written again once, then replaced by *Not found*. Answers take a second or two longer. Hidden answers are kept for audit, never shown.
- **Don't check with a model**: only level 1 runs (contacts, times and codes compared with the sources, no model, no cost).

You can change this even when the super-admin chooses the models of your customer.

### Max check tokens

How long the checking model's reply may be, for each group of up to 10 statements (long answers are checked in several groups). Empty: 2500, enough for most models. Raise it (for example to 6000) when answers often show **Check not available** and the logs say the check was *cut at the token limit* or *empty*: reasoning models such as gpt-oss spend part of the limit thinking before they reply. Like the mode, you can change it even when the super-admin chooses the models.

When a check cannot run, Mentis tries once more; the reason is written in the logs (`docker compose logs api | grep -i check`): *cut at the token limit*, *empty answer (stop: refusal)*, *timed out*, and so on.

## Usage

Below the choice, **Usage, last 30 days** shows the questions about your customers and the tokens used, per model.

## Test what analysts get

**Chat** in the left menu opens the chat on your own customers only. Use it to check that a new document version answers as expected. Your chats are private.

The **Suggested follow-up questions** and **Include the General Knowledge Base** options in **Settings** change the answers immediately.
