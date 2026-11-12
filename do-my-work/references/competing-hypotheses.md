# Competing hypotheses

Use when a bug's root cause is still unclear after reproduction, or when a bug fix has stalled (SKILL.md step 6, "Stalls"). Run it at most once per bug.

1. Write 2–4 hypotheses, each predicting something not yet examined, with at least one from a different kind of failure (data, logic, configuration or infrastructure, timing, external dependency). With fewer than two real candidates, keep investigating as one agent instead.
2. Record `git status`. Spawn one fresh researcher per hypothesis, in parallel where supported, with the researcher brief. Give each investigator only its own hypothesis and, if reports go to files, its own report path. Investigators that need to build or run tests run one at a time, or each in its own worktree. Without subagents, test the hypotheses yourself one at a time.
3. Once all have reported, compare `git status` with the record, ignoring the report files. If anything else changed, show the user the diff before going on, revert nothing yourself, and treat that investigator's report as unreliable.
4. Rank the reports by concrete evidence, not plausibility, and weigh evidence against as heavily as evidence for. Conclude one of:
   - **Confirmed:** the cause goes into the approach you present (SKILL.md step 3), or into the fix if implementation is already approved. A fix that works while the hypothesis's prediction failed is a symptom fix, not a confirmation.
   - **Compound:** several causes; fix them in dependency order.
   - **Inconclusive:** say what the pattern suggests (hypotheses spread across subsystems suggest a design problem, contradictory evidence a wrong model of the code, a local pass with a CI failure an environment difference), propose an experiment that would separate the hypotheses, and ask the user.
5. If the fix for the leading hypothesis fails, try the runner-up. If that fails too, stop and ask the user.
