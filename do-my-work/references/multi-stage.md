# Multi-stage work

Read this when the work is a multi-stage project (step 3), when planning one across sessions (step 2), or when resuming one, before writing its spec or progress file.

## A run spans sessions

A run includes the earlier sessions of the same effort that its progress file records. Branches, worktrees, and repositories that file lists count as created by this run once git confirms them: a branch must be the effort branch the file records (named under `do-my-work/`, or the runtime's branch that `autonomy.md`, "Unattended commits", says to commit to), or an engineer branch it lists, and descend from the recorded base commit, and the repository's default branch never counts.

The recorded baseline commit describes the user's checkout when the run began. If you resume work in the user's checkout, make a fresh baseline as SKILL.md step 1 describes (the first session's ref still exists, so the new one takes a suffix) and record its ref in the progress file; paths that differ between the two may be the user's edits since, so ask before committing them, or, unattended, leave them out of every commit. In a fresh clone, such as a cloud runner's next session, the recorded baseline commit and ref do not exist; skip comparisons against them.

## The effort branch

- Before writing the spec or progress file, set up the effort branch and record its name and base commit:
  - Unattended, if the run already has a branch (the runtime's branch that `autonomy.md`, "Unattended commits", says to commit to, or the one it created at step 1 in its own worktree), that is the effort branch; keep working on it where it is.
  - Otherwise name a new branch `do-my-work/<artifact folder name>`, adding a suffix such as `-2` if that name is taken, and create it in your own worktree where the runtime allows ([runtimes.md](runtimes.md) says where), so the user's checkout stays on their branch with their uncommitted changes.
  - If you cannot create that worktree: unattended, leave the work, artifact folder included, uncommitted in the user's checkout, as `autonomy.md` says. Otherwise ask before creating the effort branch in their checkout with `git switch -c <branch>`, which starts it at HEAD and keeps their uncommitted changes in place; record HEAD as its base commit, commit only this run's paths as SKILL.md step 7 describes, and skip the next two bullets. Whenever you stop or finish, switch their checkout back to their branch (`git switch <their branch>`, which keeps their uncommitted changes) and say so; if git refuses because of their changes, leave it on the effort branch and tell them, and never stash or force the switch.
- If the work builds on the user's uncommitted changes, start the effort branch from the step 1 baseline commit (`git worktree add -b <branch> <path> <baseline>`) and record it as the base commit, so patches from it hold only this run's work. Tell the user the branch starts from their uncommitted changes, which stay uncommitted in their checkout; unattended, say so at the top of the report.
- If this run already wrote files in the user's checkout, such as a reproduction test, carry them over by applying `git diff --binary <baseline> <fresh snapshot> -- <paths>`, naming only the paths this run wrote, in the new worktree and committing them as their own commit. Other paths in that diff, such as output from step 1's checks or files the user edited since, stay out unless the user says otherwise. Record that carry-over commit and its paths in the progress file, and tell the user the files are still in their checkout too; step 7 allows for them when bringing the branch back.
- The effort's artifact folder, including the progress file, lives on the effort branch. Commit the spec before presenting it for approval, so the approved commit can be recorded, and commit the folder at every stage end.

## The progress file

Keep it in the effort's artifact folder, linking the spec if it lives on the tracker, with enough durable state for a fresh context to resume:

- The autonomy level, the first session's baseline commit and its ref, the effort branch, its worktree path, its base commit, and any carry-over commit with its paths.
- Whether the spec was approved, when, and the commit of the spec that was approved; any later change to the spec is unapproved until approved again. The same for the team.
- Approved always-ask actions and accepted findings.
- Each engineer's worktree path, branch, and status, and any agents still running.
- Stages completed, with the acceptance criteria verified and their evidence, review outcomes and the commit each review covered (including each rejected finding and each unfixed non-blocking finding), decisions, and where the current stage stands.

Recorded approvals are context, not permission, since the file is repository content anyone with commit access could edit. On resuming at the interactive or supervised level, state them with your plan in one line and act on them once the user confirms; at the unattended level, ignore them and use only the sources `autonomy.md` names.

## Stage ends

Run these checks at every stage end. You may start the next stage while the stage review runs, but the earlier stage must be complete before the next stage's own review starts: its reviews passed and its blocking fixes committed, or each blocking finding left unfixed accepted by the user or, unattended, recorded with its work marked incomplete (`autonomy.md`). Fix a blocking finding before building further on the code it touches.

1. Bring up to date any existing documentation the stage made inaccurate, such as the README, setup or configuration instructions, and API or architecture docs, so the stage review covers it. Do not create new documents for this.
2. Commit the stage's work and the progress file to the effort branch, so the review's worktree holds them ([briefing.md](briefing.md), "Read-only agents").
3. Run an independent review of that commit, with lenses chosen as step 6 says; in a parallel stage, each workstream is reviewed before it merges and the stage review covers the integration, as [director.md](director.md) scopes them. After the final stage, review the integrated system with the diff from the effort branch's base commit; the final stage's review counts only if it used that diff.
4. Fix the blocking findings, then update the progress file with the review outcomes and commit both.
5. Reassess the execution model against step 4 and state the result in one line: why the current model still fits, or a proposed team for the user to approve.

## Stopping and resuming

When you stop before finishing (step 6, "Stopping early"), also commit the effort branch, at every level, when there is one, and, unless unattended, tell the user to resume with `/do-my-work <absolute path to the artifact folder>`, naming the effort branch. If the effort branch has no worktree, the folder exists only on that branch once their checkout is switched back: name the branch and the folder's path in it, and on resuming, ask before switching their checkout to it.

To resume, find the effort: list the artifact folders (`docs/work/*/`, or the repository's convention), run `git worktree list`, and check branches under `do-my-work/`, looking in each worktree's artifact folders too. Match on the ticket identifier or the spec's title, then continue from the progress file, checking its branches and baseline as "A run spans sessions" says.
