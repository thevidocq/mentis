# AI providers

**AI providers** lists the LLMs Mentis uses, in two sections:

- **Answers**: the models that write the answers. The chat does not answer until at least one is configured.
- **Answer check**: the models that check every answer against its sources (level 2 of the answer check, see below). Optional.

## Add a provider

1. Click **Add provider**, choose **Use for**: *Answers* or *Answer check*, and pick a preset in **Start from**: Anthropic, OpenAI, OpenAI (Responses API), vLLM, Ollama. A preset fills the API type and the address, never a model.
2. Paste the **API key** (not needed for local Ollama or vLLM without authentication).
3. Click **Load models**: Mentis asks the provider which models it offers and lists them, newest first. Pick one. If the provider has no list, choose **Other** and type the name.
4. **Save**, then **Test**. A model for answers must answer "ready". A checker gets a sample answer with a planted error (2 hours instead of 30 minutes) and must catch it, without rejecting the correct statement.

API type, address (Base URL), reasoning effort, token limit and prices are under **Advanced**; it opens by itself when no preset filled the address.

When you edit a provider, the list is loaded with the stored key; **Reload** refreshes it, for example after the provider releases a new model.

| API type | Use for | Endpoint called |
|---|---|---|
| Anthropic Messages | Claude models | `<base>/v1/messages` |
| OpenAI Chat Completions | OpenAI, Ollama, vLLM, any compatible server | `<base>/chat/completions` |
| OpenAI Responses | OpenAI, vLLM (e.g. gpt-oss) | `<base>/responses` |

**Reasoning effort** applies to the Responses API. **Max answer tokens** limits the answer length (default 1500). **Price input/output** (USD per million tokens, optional) feed the cost estimate in **LLM usage**.

API keys are stored encrypted and never shown again; leave the field empty to keep the stored key. A stored key is only sent to the address it was saved for: when you change the **Base URL** to another server, enter the key again (a configuration import that moves a provider to another address drops its key).

## Default, tenant choice and fallback

- One model per section is the **Default**: the default for answers, and the default checker. The first model of a section becomes its default; adding another one never changes it: use **Set as default** on its row.
- The **Default** for answers answers for every customer and for **All customers** chats.
- A tenant can use another provider and a **fallback**: in **Tenants**, click the brain icon of the tenant, or the tenant admin does it in **LLM**.
- If the first model fails (down, timeout, quota), Mentis asks the fallback. The model that answered is shown under each answer.
- A provider in use by a tenant cannot be deleted.

## Answer check

Every answer is checked against the passages it cites, in two levels:

- **Level 1**, always on, no model: phone numbers, e-mail and IP addresses, times, durations, percentages, dates and codes (INC-123456) in the answer must be in the passages, compared in a normalised form ("+39 085 111 2233" = "085 1112233", "30 minuti" = "30 minutes" = "0.5 h"). An answer without citations is flagged as unverified.
- **Level 2**, a model: each statement is checked against its cited passages; added facts, changed numbers and invented steps are flagged. The model used: the checker chosen for the customer; else, for a customer with its own LLM, that LLM (its data stays with the provider it chose); else the **default checker**; else the model that wrote the answer, which re-reads its own answer: a weaker, *self* check, shown in the chat as "self-checked by …" and warned about in **Answer check** when no checker is configured. Add a different model as checker for an independent check. A small, fast model is enough. Fact-checking models such as *Bespoke-MiniCheck* (Ollama) are recognised by name and asked sentence by sentence (check their license for commercial use).

What happens when a check fails is chosen per customer (**LLM** page): show a warning (default), hide the answer, or no level 2. Analysts see under each answer which level found the problem (**Level 1**, **Level 2**, **Level 1 + 2**), with the wrong value or statement highlighted. Every check is in **Logs** (`chat.checked`: level, result, model, tokens) and its cost in **LLM usage** (rows "… · answer check").

Answers and checks are sent with temperature 0 (repeatable); models that refuse the parameter are asked again without it.

## What is sent to the model

Only the question, the last few messages of the chat and the passages found in the customer's documents. Questions without matching passages are answered "Not found" without calling the model. Logs record metadata only (customer, model, tokens, time), never questions or answers.

## Data residency

Cloud providers (Anthropic, OpenAI) receive the passages. For customers whose documents must stay internal, give them an internal model (gpt-oss on vLLM, Ollama) and no cloud fallback.

## Troubleshooting

| Error | Meaning |
|---|---|
| invalid API key (401) | Key wrong or revoked |
| access denied (403) | The account cannot use this model (some models need approval from the provider) |
| wrong URL or model (404) | Check Base URL (with `/v1` for OpenAI-compatible servers) and model name |
| rate limited (429) | Quota exceeded: wait or raise the limit |
| not reachable / timed out | Network, DNS, or the model server is down |
