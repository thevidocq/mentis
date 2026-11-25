# LLM usage

**LLM usage** shows, for the chosen period, one row per customer and AI model:

- **Questions**: questions asked, split into **answered**, **not found** and **errors**.
- **Tokens in and out**: what the model consumed.
- **Average time**: how long the model took to answer.
- **Estimated cost**.

"Not found" questions appear with LLM *none*: when the documents do not cover a question, the model is not called and costs nothing.

## Cost

The cost uses the prices you set on each provider in **AI providers** (**Price input** and **Price output**, in USD per million tokens). Leave them empty for internal models: the cost then shows **—**. Prices are not fetched automatically, so check your provider's price list.

## Where the numbers come from

They are computed from the chat events in **Logs**, so they go back as far as the log retention period. Tenant admins see the figures of their own customers on their **LLM** page, without costs.
