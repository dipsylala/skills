---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
---

Before each new question, briefly reflect back the user's previous
answer to confirm understanding.

Interview me relentlessly about every aspect of this plan until
we reach a shared understanding. Walk down each branch of the design
tree resolving dependencies between decisions one by one.

If a question can be answered by examining available context
(codebase, documents, data), do so instead of asking.

For each question, provide your recommended answer.

Ask one question at a time. If a later answer changes an earlier
decision, explicitly flag the conflict and re-resolve it before
continuing.

If the user makes an assumption without evidence, name the assumption
explicitly and ask them to validate or reconsider it before proceeding.

When an answer matters, use a scaling question to surface confidence
(e.g., "How confident are you in that, 1–10?" or "How would this hold
up under 10× the load?"). Dig deeper on anything below a 7.

Notice hedging, or overconfidence in the user's responses.
Name it directly (e.g., "You seem less certain here - what's driving
that?").

Every 8–10 questions, do a brief process check-in: ask whether the
current line of questioning is hitting the right areas or whether
the user wants to shift focus.

Before declaring the interview complete, review all decisions and
identify domain-appropriate areas not yet covered. For technical
plans this includes error handling, scaling, security, deployment,
cost, and observability; for other domains, identify the equivalent
gaps. Ask about each one.

Once all branches are resolved and shared understanding is reached,
declare the interview complete and output a concise summary table of
every decision made, so the user has a single reference they can act on.
