---
name: grill-with-docs
description: Interview the user about a plan or design while recording agreed architectural decisions and domain vocabulary in ADRs and a glossary.
disable-model-invocation: true
---

## Process

Work through consequential decisions in dependency order. Maintain a record of agreed decisions and open questions, and update the documents as decisions are resolved.

1. Read the relevant repository context, existing ADRs, and glossary. Reuse the project's documentation locations and formats. If none exist, use `docs/decisions/` for ADRs and `docs/GLOSSARY.md` for vocabulary.

2. Interview the user one decision at a time, asking one question at a time. Resolve factual questions from available sources before asking. Briefly reflect the previous answer, explain the next decision's tradeoffs, and recommend an answer when evidence supports one; otherwise explain what evidence is missing. If a later answer conflicts with an earlier decision, flag and resolve the conflict before continuing.

   Identify consequential assumptions that lack evidence and claims whose certainty exceeds the available evidence. Explain the evidence gap and ask whether the decision should remain provisional. Use confidence questions when uncertainty could change a consequential decision, investigating in proportion to its impact. Use load scenarios separately when scale matters.

   Every 8-10 questions, briefly ask whether the current line of questioning is covering the right areas or whether the user wants to shift focus.

3. Create an ADR for decisions with meaningful architectural consequences or alternatives worth preserving. Record minor clarifications in existing documents. After each agreed architectural decision that meets this criterion, create or update an ADR with its title, status, context, decision, consequences, and source references. Record proposals and unresolved questions as drafts. Preserve superseded decisions and link to their replacements rather than silently rewriting their history.

4. Maintain the glossary as terms are agreed. For each term, record its meaning in this project and distinctions from related terms. Separate suggested vocabulary from accepted definitions. Update existing entries rather than creating duplicates.

5. When a decision changes, reconcile the affected ADRs and glossary entries after resolving the conflict. Preserve superseded ADRs and link their replacements. Do not leave conflicting decisions presented as current.

6. Before declaring the interview complete, review all decisions and identify relevant areas not yet covered. For technical plans, review error handling, scaling, security, deployment, cost, observability, and testing; for other domains, identify equivalent concerns. Ask about consequential gaps that cannot be resolved from available sources.

Finish when each consequential decision is agreed or explicitly deferred with its implementation impact recorded, shared understanding is reached, and the documents reflect the current decision record. Declare the interview complete and return a concise summary table of every decision made, including its status and relevant document links, plus document paths and remaining blockers. If the user stops early, preserve the partial documents and return the partial decision table and open questions without declaring the interview complete.
