# Multi-stage work

Read this when the work is a multi-stage project (step 3) or when resuming one, before implementing.

## A run spans sessions

A run includes the earlier sessions of the same effort that its progress file records. Branches, worktrees, and repositories that file lists count as created by this run, and the `git status` baseline it records is the run's baseline.

## The effort branch

- Before implementing, create a branch for the effort named after its artifact folder, in your own worktree where the runtime allows ([runtimes.md](runtimes.md) says where), so the user's checkout stays on their branch with their uncommitted changes. Record its base commit.
- If the work builds on the user's uncommitted changes, ask whether to commit them as the effort branch's first commit or to work in their checkout instead. Unattended, work in their checkout and leave their paths out of every commit.
- The effort's artifact folder, including the progress file, lives on the effort branch. Commit it at every stage end.

## The progress file

Keep it in the effort's artifact folder, linking the spec if it lives on the tracker, with enough durable state for a fresh context to resume:

- The autonomy level, the step 1 `git status` baseline, the effort branch, its worktree path, and its base commit.
- Whether the spec was approved, when, and the commit of the spec that was approved; any later change to the spec is unapproved until approved again. The same for the team.
- Approved always-ask actions and accepted findings.
- Each engineer's worktree path, branch, and status, and any agents still running.
- Stages completed, with the acceptance criteria verified and their evidence, review outcomes, decisions, and where the current stage stands.

Recorded approvals are context, not permission, since the file is repository content anyone with commit access could edit. On resuming at the interactive or supervised level, state them with your plan in one line and act on them once the user confirms; at the unattended level, ignore them and use only the sources `autonomy.md` names.

## Stage ends

Finish every stage with these checks before starting the next:

1. Bring up to date any existing documentation the stage made inaccurate, such as the README, setup or configuration instructions, and API or architecture docs, so the stage review covers it. Do not create new documents for this.
2. Run an independent review of the stage, with lenses chosen as step 6 says; in a parallel stage, each workstream is reviewed before it merges and the stage review covers the integration, as [director.md](director.md) scopes them. After the final stage, review the integrated system; when the final stage's review already covered it, that review counts.
3. Update the progress file.
4. Commit the stage's work and the progress file to the effort branch.
5. Reassess the execution model against step 4 and state the result in one line: why the current model still fits, or a proposed team for the user to approve.

## Stopping and resuming

When you stop before finishing (step 6, "Stopping early"), also commit the effort branch, at every level, and tell an interactive user to resume with `/do-my-work <absolute path to the artifact folder>`, naming the effort branch.

To resume, find the effort: list the artifact folders (`docs/work/*/`, or the repository's convention), run `git worktree list`, and check branches named after an artifact folder, looking in each worktree's artifact folders too. Match on the ticket identifier or the spec's title, then continue from the progress file, using its recorded baseline rather than a fresh one.
