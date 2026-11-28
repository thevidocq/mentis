# Customer settings

Open **Settings**. Changes apply at once.

## Include the General Knowledge Base

On by default. Answers also use the General Knowledge Base (general knowledge shared by all customers, maintained by the SOC). When it and your procedures disagree (escalation, SLA), your procedure wins. Turn it off if answers for your customer must use only your documentation; analysts can also turn it off for a single chat. When it is off, **All my customers** chats that include your customer do not use the General Knowledge Base either.

## Approve new document versions before publishing

Off by default. When on, a newly uploaded version stays inactive until you approve it in the preview, so a badly read file never replaces a good one by surprise.

## Approval by another person

Off by default. When on, a version waiting for approval must be approved by someone other than the person who uploaded it (that person can still reject it). It applies only when versions wait for approval: with **Approve new document versions before publishing** on, or always for the General Knowledge Base. Approving your own upload while it is off is allowed and recorded in the logs.

## Suggested follow-up questions

On by default. Shows 2–3 clickable questions under each answer, based only on what your documentation can answer.

## Passages read per answer

Empty by default: the platform value (8, set by the operator) applies. For each question Mentis gives the AI the passages of your documentation (and of the General Knowledge Base) closest to the question; this number says how many, from 3 to 20.

- **Raise it** (e.g. 12–15) when analysts ask several things in one question or your procedures are long and split across many sections: with too few passages part of the question may find nothing.
- **Lower it** when answers mix in unrelated procedures.

More passages mean slightly slower and more expensive answers. Use **Test a question** on a document to see which passages a question finds.

## Questions that ask several things

**Normal** by default. Decides how Mentis chooses the passages above.

Without it, Mentis takes the passages closest to the whole question. When a question asks two things at once ("how do I handle this CVE, and who is the on-call contact?"), the stronger topic can take every place and the other finds nothing, so the answer says it does not know.

With it, Mentis reads more candidates and picks them one at a time: each passage must be relevant to the question **and** add something the passages already picked do not say. Near-duplicates give way, and the second request gets its passages.

- **Normal**: the right balance for most customers. Questions about one thing get the same answers as before.
- **High**: more room for the second topic; use it if analysts often combine requests. On a long procedure a step similar to another may give way to a different passage.
- **Off**: only the passages closest to the whole question, as in earlier versions.

It is an established search technique (*Maximal Marginal Relevance*): deterministic, no extra AI call, nothing to re-index. Splitting a question by its punctuation would be guesswork; this looks only at how similar the passages are. If a second request still finds nothing, ask it on its own or raise **Passages read per answer**.

## Integration lookups

Decides how Mentis chooses what to read in your customer's tools (ticketing, EDR, identity) when an analyst uses integrations with `#`. Both modes are read only, use only this customer's integrations, check every argument (ticket number, host, user) against its expected format, and record every lookup in the audit log. The answer is written in the same way in both modes, with citations, links to the records and the answer check.

### Standard (default)

Mentis decides the lookups **before reading any customer data**:

1. Identifiers with an unmistakable shape (ticket numbers, issue keys, alert ids) are read directly, without the AI model.
2. One short call to the AI model adds the lookups the question needs, such as a host, a user, open alerts or a search.

**Strengths**: works with every AI model, including internal ones (Ollama, vLLM/gpt-oss); costs one short model call per question; text written inside tickets and alerts can never trigger a lookup.
**Limit**: lookups do not build on each other. If a ticket names a host, Mentis does not read that host's alerts by itself: the analyst asks a follow-up question (*"and the alerts of that host?"*), which works because the previous answer is part of the conversation.

### Function calling

The AI model works through the lookups step by step: it reads each result and can ask for further lookups, for example the host named in a ticket and then that host's alerts, up to **3 steps and 8 lookups per question**. Identifiers in the question are still read first, without the model.

**Strengths**: one question can follow the thread (ticket → host → alerts → user sign-ins).
**Requirements**: an AI model with function calling: Anthropic and OpenAI models, and vLLM or Ollama models that support it. If the model or provider does not, Mentis uses Standard for that question and records `integration.tools_unavailable` in the logs; the analyst still gets an answer.
**Cost**: up to three model calls per question, instead of one.
**Risk to accept**: tickets and alerts can contain text written by users or attackers. The model is instructed to treat it as data, but such text can still lead it to an extra lookup: at most another read of **this customer's** data, read only and logged. It can never change anything, reach another customer or another address, or make the answer show a link that is not a record found.

### Who chooses

Function calling depends on the AI model, so it is chosen by whoever chooses the model: you, when the customer uses its own LLM chosen in **LLM**; otherwise a super-admin. When you cannot change it, the page says why. A change applies to the next questions.

**Recommendation**: keep **Standard** unless analysts often need to follow a ticket to its host or user in one question and the customer's model supports function calling.
