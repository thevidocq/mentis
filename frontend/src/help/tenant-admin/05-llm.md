# LLM and testing answers

## Choose the LLM

**LLM** in the left menu chooses which AI model writes the answers about your customer.

- **LLM for answers**: *Platform default* uses the model chosen by the super-admin. Pick another one from the list if your customer needs it, for example an internal model (gpt-oss, Ollama) when documents must not reach a cloud provider.
- **Fallback when it fails**: used only if the first model does not respond. Leave it on *None*, or pick an internal one, if the customer's data must stay internal.

The list shows the models added by the super-admin. Analysts see the model's name under each answer.

## Usage

Below the choice, **Usage, last 30 days** shows the questions about your customer, the tokens used and the estimated cost, per model.

## Test what analysts get

**Chat** in the left menu opens the chat on your own customer only. Use it to check that a new document version answers as expected. Your chats are private.

The **Suggested follow-up questions** and **Include General documentation** options in **Settings** change the answers immediately.
