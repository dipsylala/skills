# Briefing agents

Read this before you spawn the first agent of a run.

## The spawn prompt

Every spawn prompt contains:

- The task and its inputs.
- The absolute path to the role's brief in [briefs/](briefs/) (`researcher.md`, `tester.md`, `engineer.md`, or `reviewer.md`), with this line: "Read it and the `all-agents.md` beside it first. If you cannot read either, do nothing else and reply `BLOCKED: brief unreadable`." If the agent cannot read files at all, paste both instead.
- The always-ask list from `all-agents.md`, pasted, since it is short and must reach the agent even when its file access is limited. Name any always-ask action already approved for this agent; authorise one only once it is approved.
- The known pre-existing failures from step 1, for testers, engineers, and reviewers.
- For engineers and workstream reviewers in model C, the decisions log's absolute path in your checkout.
- For multi-stage work, an absolute path for the report file in a `reports/` folder inside the effort's artifact folder, so reports survive the context and reach you from an engineer's worktree. Add that folder to the exclude file `git rev-parse --git-path info/exclude` prints (in a linked worktree, `.git` is a file) so reports are never committed, and record their outcomes in the progress file.
- For a reviewer that needs the running app, such as a user-experience reviewer, a free port to start it on in its own worktree.
- For an agent working in a worktree, the commit it should start at, with this line: "Before anything else, check that `git rev-parse HEAD` prints that commit; if not, do nothing else and reply `BLOCKED: wrong commit`." A runtime's worktree option may start somewhere else, such as your checkout's HEAD; if an agent replies this, create its worktree yourself at the commit and spawn it again with that path.

If an agent cannot reach paths in your checkout, paste the decisions log and later updates into its prompt, take its report as its reply, and write the report file yourself.

## Acting on reports

- Act on each report's first line and read further only when acting on it: `STATUS: READY|PLAN|BLOCKED` from engineers and researchers (and `STATUS: READY|BLOCKED` from a subordinate director), `RESULT: PASS|FAIL|BLOCKED` from testers, `VERDICT: PASS|CHANGES` from reviewers.
- Always read a reviewer's findings, which step 7 reports.
- If an agent replies `BLOCKED: brief unreadable`, spawn it again with both briefs pasted into the prompt.
- Send follow-up work (an approved or returned plan, a failed gate, review fixes) to the same agent where the runtime allows. Otherwise spawn a fresh agent of that role with its earlier report and the new input and, for an engineer, its original worktree path and branch.

## Read-only agents

Researchers, testers, and reviewers make no edits. Check that they did not:

- **Preferred:** run each in its own worktree at a recorded commit that holds the work it checks, created where [runtimes.md](runtimes.md) says, and have it report its evidence against that commit. A worktree holds only committed work, so make the work a commit first, and give the agent that commit as "The spawn prompt" says:
  - On a branch this run created, commit it there.
  - Otherwise, such as uncommitted work in the user's checkout, make a snapshot commit without touching their index: with `GIT_INDEX_FILE` set to a temporary file, run `git read-tree HEAD`, `git add -A`, and `git write-tree`; then run `git commit-tree <tree> -p HEAD -m snapshot` without it, and create the worktree detached at the commit it prints (`git worktree add --detach <path> <commit>`).
  - If you cannot do either, share the checkout as below.
- Afterwards, the worktree's HEAD must still be the recorded commit and `git status --porcelain` there must list nothing but its report file; anything else is its own write. A hypothesis researcher's throwaway logging there is allowed and never merged. Reviewers that need the running app start it in their own worktree on the port you give them, not in a checkout you are still editing.
- **When it must share a checkout** (the runtime cannot create worktrees): keep the checkout unchanged while it works, and run no other agent in it. Before spawning, record `git rev-parse HEAD`, `git status --porcelain`, `git diff HEAD | git hash-object --stdin`, and `git ls-files -o --exclude-standard | git hash-object --stdin-paths` (the contents of untracked files); afterwards, any difference other than its report file means it wrote. Paths git ignores, such as build and test output, don't count.
- A tester's run that changes a lockfile or snapshot is a finding about the test setup, reported as such, not a write by the tester. Keep that change out of every commit too.
- If an agent wrote, show the user the diff, revert nothing yourself, treat its report as unreliable, and keep its changes out of every commit until the user decides.

## Choosing models

Where the runtime lets you choose each agent's model, choose by how much judgement its task needs; otherwise every agent runs on the session's model.

- **Fast model:** a researcher searching code or summarising documents; a tester running suites and reporting results.
- **Mid-tier model:** a researcher testing a debugging hypothesis; an engineer making mechanical edits from a precise specification; a user-experience reviewer; an engineer writing tests for subtle behaviour.
- **Strongest model:** design; a plan reviewer; foundation stages; an engineer on shared or core code or intricate logic; a correctness or security reviewer of a risky change. A correctness or security reviewer is never on a weaker model than the engineer whose work it reviews.

When unsure, choose the stronger model.

## Agent timeline

When you first spawn an agent in a run, if an `agent-timeline` skill folder sits beside this skill's folder, follow the "Run it" section of its `SKILL.md` without `--open`, and give the user the URL once. It only reads, and changes nothing about how agents run. It works only on Claude Code; skip it elsewhere. If it fails to start, say so once and continue.
