# AI providers

**AI providers** lists the LLMs that write the answers. The chat does not answer until at least one is configured.

## Add a provider

1. Click **Add provider** and pick a preset in **Start from**: Anthropic, OpenAI, OpenAI (Responses API), vLLM, Ollama. A preset fills the API type and the address, never a model.
2. Check **Base URL** and paste the **API key** (not needed for local Ollama or vLLM without authentication).
3. Click **Load models**: Mentis asks the provider which models it offers and lists them, newest first. Pick one. If the provider has no list, choose **Other** and type the name.
4. **Save**, then **Test**: the model must answer "ready".

When you edit a provider, the list is loaded with the stored key; **Reload** refreshes it, for example after the provider releases a new model.

| API type | Use for | Endpoint called |
|---|---|---|
| Anthropic Messages | Claude models | `<base>/v1/messages` |
| OpenAI Chat Completions | OpenAI, Ollama, vLLM, any compatible server | `<base>/chat/completions` |
| OpenAI Responses | OpenAI, vLLM (e.g. gpt-oss) | `<base>/responses` |

**Reasoning effort** applies to the Responses API. **Max answer tokens** limits the answer length (default 1500). **Price input/output** (USD per million tokens, optional) feed the cost estimate in **LLM usage**.

API keys are stored encrypted and never shown again; leave the field empty to keep the stored key. A stored key is only sent to the address it was saved for: when you change the **Base URL** to another server, enter the key again (a configuration import that moves a provider to another address drops its key).

## Default, tenant choice and fallback

- The **Default** provider (star icon to change it) answers for every customer and for **All customers** chats.
- A tenant can use another provider and a **fallback**: in **Tenants**, click the brain icon of the tenant, or the tenant admin does it in **LLM**.
- If the first model fails (down, timeout, quota), Mentis asks the fallback. The model that answered is shown under each answer.
- A provider in use by a tenant cannot be deleted.

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
