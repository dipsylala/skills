---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
---

Interview me relentlessly about every aspect of this plan until
we reach a shared understanding. Walk down each branch of the design
tree resolving dependencies between decisions one by one.

If a question can be answered by exploring the codebase, explore
the codebase instead.

For each question, provide your recommended answer.

Ask one question at a time. If a later answer changes an earlier
decision, explicitly flag the conflict and re-resolve it before
continuing.

Once all branches are resolved and shared understanding is reached,
declare the interview complete and output a concise summary table of
every decision made, so the user has a single reference they can act on.
