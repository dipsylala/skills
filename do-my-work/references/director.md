# Director with engineering team (model C)

Read this when you choose model C in step 4, before proposing the team. As director you own the overall specification, decomposition, interface contracts, dependencies, workstream assignments, integration decisions, and final acceptance verification.

## Setting up

- **Workstreams:** give each engineer an explicitly bounded implementation area and its local tests, in distinct files or modules or an isolated worktree, with its expected outputs and interfaces defined before work starts. Workstreams that need substantial changes to the same files are not independent; run them one after another. Give small shared touch points (a route table, an index) to one owner under the shared-file policy.
- **Team size:** one engineer per independent workstream, at most 5, each with self-contained tasks and a clear deliverable.
- **Integration plan:** define the merge and integration owner, the shared-file policy, the dependency order, and the integration tests. Keep edits and build operations coordinated: you never modify files an engineer owns while it works, and ownership changes are agreed explicitly before overlapping edits.
- **Rollback point:** before starting parallel engineers, commit the work they build on to the effort branch ([multi-stage.md](multi-stage.md)), since worktrees hold only committed work, and record that commit in the progress file as the point to return to if the stage fails. Start each engineer's worktree at that commit, checked as [briefing.md](briefing.md), "The spawn prompt", says, and set up as its "Setting up a worktree" says. Commits on the effort branch need no go-ahead (step 7).

## Decisions log

Keep one in the effort's artifact folder, holding the interface contracts and every decision that binds more than one workstream. Only you write it. Give each engineer and each workstream reviewer its absolute path in your checkout, not in an engineer's worktree, so they always read the current version.

When an engineer reports `BLOCKED` on a decision another workstream could see that the log does not settle, decide it, add it to the log, and tell every engineer it affects before their next round.

## Running the workstreams

- **Plan-first:** for a risky workstream (shared or core code, anything step 3 requires approval for, a change many other parts depend on, or one that is hard to undo), tell the engineer to plan first; the engineer brief says what the plan contains. Approve the plan when it covers the workstream's acceptance criteria, agrees with the decisions log, stays inside the workstream's files, gives every step a check, and leaves no open questions or TBDs; otherwise return it with reasons. Do not rely on a runtime's plan mode to enforce this, since some approve plans automatically.
- **Completion gate:** put each workstream's gate commands (the tests, lint, type checks, and build it must pass) in its brief, with the known pre-existing failures from step 1; a run is clean when nothing else fails. Before accepting an engineer's `STATUS: READY`, check that its worktree has no uncommitted changes apart from the untracked files its setup left, and that its branch is at the commit it reported; if not, return it. Then you or a fresh tester re-run the gate commands at that commit; accept only a clean run, or a tester's `RESULT: PASS`. Otherwise return it to the engineer with the output. The workstream review and the merge use the same commit.
- **Rounds and stalls:** a round is one brief or revision sent to an engineer and one report back. A workstream is stalled when two consecutive rounds show the same failure, or no new gate command passing and no failure narrowed; when its plan has been returned twice; or when its engineer reports `BLOCKED` after two failed attempts at the same failure. Handle a stall as step 6's "Stalls" says.
- Check progress at meaningful milestones and redirect work that is going off course. Talk to engineers directly, in short evidence-based updates.

## Integrating

Integrate on the effort branch (`multi-stage.md`), not the user's branch; bringing it into the user's branch follows step 7. Integrate workstreams one at a time as each finishes, rather than all at the end: pass its completion gate, review it independently, fix its blocking findings (the engineer commits the fixes and reports the new commit), then merge that commit with `git merge --no-commit --no-ff` and run the integration tests before committing. If they pass, commit the merge and tell each remaining engineer to merge the integrated result into its worktree at the start of its next round. If the merge conflicts or the tests fail, run `git merge --abort` (it undoes only your own uncommitted merge, so it is not an always-ask action), tell no other engineer to merge, and return the failure to the engineer whose workstream it is as its next round; fix it yourself only when no engineer owns the files involved. If a merge that already landed has to be reverted, revert the revert before merging that workstream again, or its original changes stay out.

Review each workstream with the correctness lens plus any other lens its own changes trigger (step 6). The stage review then covers the integration: correctness across workstreams, plus lenses that changes spanning workstreams trigger. Skip the stage review when the stage was a single workstream that has already been reviewed. Spawn fresh adversarial reviewers as model B defines them, one per lens, never standing team members. Use researchers and testers only where they add value. Neither an engineer's self-review nor your review of integration is independent.

## Subordinate director (model D)

Exceptional: only for a substantial, independently bounded programme or repository within a larger effort, owning a distinct outcome rather than duplicating your coordination. Before proposing one, identify its scope, authority, subordinate agents, decision and escalation boundaries, communication contract, and why direct coordination is insufficient, and get explicit user approval. If nested delegation is unsupported, keep coordination yourself.

Brief it with this skill folder's absolute path (it follows `SKILL.md`, this file, and the references they name, and `briefs/all-agents.md` applies to it), its scope, the runtime capabilities you found, your autonomy level, the step 1 baseline commit, and its own branch from the effort branch in its own worktree, so the two of you never integrate in one checkout. Ask it to start each report with `STATUS: READY` or `STATUS: BLOCKED`, giving its commit on `READY`; integrate that commit as you would a workstream's. It runs at your autonomy level and treats you as its user. Answer its questions yourself, but relay always-ask actions, product decisions, and team changes to the user. It skips step 1's level and runtime detection and the tracker and commit actions of steps 5 and 7, which stay yours, and it may spawn the team you approved for it.
