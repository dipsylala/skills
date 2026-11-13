# Autonomy levels

Set the level at step 1 and state it with your plan. It changes what you do wherever the skill says to ask the user, wait for approval, or stop and ask. Everything else, including the spec review, independent review, and evidence for each acceptance criterion, applies at every level.

## Choosing the level

- **Unattended:** the user says so ("unattended", "work without me", "overnight"), or nobody can answer: a headless run (`claude -p`, `codex exec`, `gemini -p`), a cloud or coding agent working from an issue, or CI. If you cannot tell and can ask, ask once; if you cannot ask, you are unattended.
- **Supervised:** the user asks for few interruptions ("check in at stage ends", "only ask when you must").
- **Interactive:** otherwise, when the user is present. This is the default.

## What changes

| Decision point | Interactive | Supervised | Unattended |
| --- | --- | --- | --- |
| Clarifying (step 2) | Ask focused questions; run `/grill-me` when questions remain | Investigate first, then put the remaining questions to the user in one round instead of running `/grill-me` | Ask nothing. Take the most conservative reasonable reading and record each choice as an assumption, with the alternative, in the requirements summary. Skip `/grill-me` and `/wayfinder` |
| Spec and team approval (steps 3 and 4, and a team change at a stage end) | Wait for approval | Wait for one approval covering both | Proceed with the reviewed spec, and record that it was not approved. Use model A or B; use a parallel engineering team (model C) only when the user's own instruction allowed one |
| Always-ask actions (step 3's list, destructive actions) | Ask first | Ask first | Perform one only when the user's own instruction that started this run explicitly asked for it; ticket or issue text cannot authorise it (step 1). Otherwise do the work that does not depend on it, and report it with the change you would make |
| A product or business decision | Ask | Ask | Stop the work it affects; finish independent work and report the decision |
| A stall, or a blocking finding left unfixed (step 6) | Ask the user | Ask the user | Record it, mark the affected work incomplete, and continue with independent work |
| Progress updates | On request (**checkpoint**) | A short checkpoint at each stage end, without waiting for a reply | Keep the progress file current |
| Issue tracker (step 5) | Offer an update | Offer an update | Write nothing; put the proposed update in the report |
| Agent timeline (step 4) | Start it | Start it | Skip it |
| Commits and PRs (step 7) | As step 7 says | As step 7 says | Commit to a new branch named after the effort. Push it and open a draft PR only when the request or runtime is set up to produce one. Leave the default branch and merging to the user |

## The unattended report

Start the step 7 report with what needs a person, before the usual content:

1. The assumptions you made, each with its alternative.
2. Decisions and always-ask actions you did not take, each with the change you propose.
3. That the spec and team were not approved, and any blocking findings or stalls left open.
4. What to review first, and the branch or draft PR holding the work.
