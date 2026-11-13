# Director with engineering team (model C)

Read this when you choose model C in step 4, before proposing the team. As director you own the overall specification, decomposition, interface contracts, dependencies, workstream assignments, integration decisions, and final acceptance verification.

## Setting up

- **Workstreams:** give each engineer an explicitly bounded implementation area and its local tests, in distinct files or modules or an isolated worktree, with its expected outputs and interfaces defined before work starts. Workstreams that need substantial changes to the same files are not independent; run them one after another. Give small shared touch points (a route table, an index) to one owner under the shared-file policy.
- **Team size:** one engineer per independent workstream, at most 5, each with self-contained tasks and a clear deliverable.
- **Integration plan:** define the merge and integration owner, the shared-file policy, the dependency order, and the integration tests. Keep edits and build operations coordinated: you never modify files an engineer owns while it works, and ownership changes are agreed explicitly before overlapping edits.
- **Rollback point:** before starting parallel engineers, make sure the work they build on is committed, since worktrees start from a commit, and record that commit in the progress file as the point to return to if the stage fails. When the commit needs the user's go-ahead (step 7), ask for it in the team proposal.

## Decisions log

Keep one in the effort's artifact folder, holding the interface contracts and every decision that binds more than one workstream. Only you write it. Give each engineer and each workstream reviewer its absolute path in your checkout, not in an engineer's worktree, so they always read the current version.

When an engineer reports `BLOCKED` on a decision another workstream could see that the log does not settle, decide it, add it to the log, and tell every engineer it affects before their next round.

## Running the workstreams

- **Plan-first:** for a risky workstream (shared or core code, anything step 3 requires approval for, a change many other parts depend on, or one that is hard to undo), tell the engineer to plan first; the engineer brief says what the plan contains. Approve the plan when it covers the workstream's acceptance criteria, agrees with the decisions log, stays inside the workstream's files, gives every step a check, and leaves no open questions or TBDs; otherwise return it with reasons. Do not rely on a runtime's plan mode to enforce this, since some approve plans automatically.
- **Completion gate:** put each workstream's gate commands (the tests, lint, type checks, and build it must pass) in its brief. Before accepting an engineer's `STATUS: READY`, you or a fresh tester re-run them in the engineer's worktree. If the re-run fails, return it to the engineer with the output.
- **Rounds and stalls:** a round is one brief or revision sent to an engineer and one report back. A workstream is stalled when two consecutive rounds show the same failure, or no new gate command passing and no failure narrowed; when its plan has been returned twice; or when its engineer reports `BLOCKED` after two failed attempts at the same failure. Handle a stall as step 6's "Stalls" says.
- Check progress at meaningful milestones and redirect work that is going off course. Talk to engineers directly, in short evidence-based updates.

## Integrating

Integrate workstreams one at a time as each finishes, rather than all at the end: pass its completion gate, review it independently (step 6), fix its blocking findings, merge it, run the integration tests, then tell each remaining engineer to merge the integrated result into its worktree at the start of its next round.

Use researchers and testers only where they add value. For each review step 6 requires, spawn fresh adversarial reviewers as model B defines them, one per lens, never standing team members. Neither an engineer's self-review nor your review of integration is independent.
