# Do My Work

Takes a software task, such as an idea, bug report, tracker issue, or spec,
through to a verified change. It clarifies requirements, designs, implements,
tests, and reviews the work. It scales the process and the agent team to the
work: one agent for a small fix, an implementer with specialists for a
coherent task, and a director with parallel engineers only when workstreams
are genuinely independent.

The skill is user-invoked. It runs on Claude Code and Codex, and relies on no
feature that only one of them has.

## Usage

```text
/do-my-work PROJ-123
/do-my-work Fix the CSV export dropping rows with commas in quoted fields
/do-my-work docs/work/csv-export/spec.md
```

The skill asks for approval at the points that matter: the specification and
approach, the team before spawning parallel engineers, and any change to
authentication, payments, CI, schemas, dependencies, or production data. It
never transitions or closes a ticket, and commits to your branch only when
asked.

## Workflow

1. **Understand** the request, reading the ticket, code, and tests, and
   reproducing any bug.
2. **Clarify** until every acceptance criterion says how to check it. When
   questions remain, this step runs `/grill-me` if it is installed, or offers
   `/wayfinder` for planning too large for one session.
3. **Specify** and present the approach. Multi-stage work gets a spec and
   progress file in `docs/work/<ticket-or-feature>/`, and a fresh reviewer
   checks the spec and stage plan before you approve them.
4. **Choose an execution model** and propose the team. Before parallel
   engineers start, the commit they build on is recorded as a rollback point.
   If the `agent-timeline` skill is installed, its live view starts when the
   first agent is spawned.
5. **Offer to update the ticket** with agreed clarifications.
6. **Execute and verify**: tests first, then, for risky or substantial
   changes, independent review by fresh reviewers, one per lens (correctness,
   security, user experience). Each stage of multi-stage work ends by bringing
   affected docs up to date before its review.
7. **Finish** with each acceptance criterion and its evidence.

| Execution model | When |
| --- | --- |
| A. Solo implementer | Small, clear, tightly bounded changes |
| B. Implementer with specialists | One coherent task that gains from isolated research, testing, or review |
| C. Director with engineering team | Several genuinely parallel workstreams with clear ownership |
| D. Subordinate director | Exceptional: a separately bounded programme inside a larger effort |

Say **checkpoint** at any time for progress, blockers, and whether the team is
paying off.

## Structure

- [`SKILL.md`](SKILL.md) holds the workflow and the rules for each execution
  model.
- [`references/briefs/`](references/briefs/) holds one brief per spawned role
  (`engineer.md`, `researcher.md`, `tester.md`, `reviewer.md`), plus
  `all-agents.md`, which every brief loads for the untrusted-input rule and the
  report format. Each report starts with a line the director acts on, such as
  `STATUS: READY` or `VERDICT: CHANGES`.
- [`references/competing-hypotheses.md`](references/competing-hypotheses.md) is
  the debugging procedure for bugs whose cause stays unclear.

## Design choices

- **The simplest team that works.** A large task does not by itself justify
  parallel engineers. Tight coupling and unstable interfaces make one
  implementer faster, so shared foundations are built first and fanned out
  afterwards.
- **The invoking agent is the director.** Model C turns the main agent into
  the director rather than adding a supervisor above it.
- **Reviews are independent.** Reviewers get the requirements, diff, and test
  evidence, but not the implementer's reasoning. Neither self-review nor the
  director's review of integration counts as independent.
- **Parallel writers share decisions explicitly.** In model C the director
  keeps a decisions log that only it writes. Engineers report unplanned
  decisions another workstream could see. This targets the main failure of
  parallel agents: conflicting implicit decisions.
- **Readiness is verified, not reported.** Each workstream's brief names its
  gate commands, and the director or a fresh tester re-runs them before
  accepting `READY`.
- **Repetition is a stall.** In any execution model, two attempts at the same
  problem without new evidence are a stall. The agent changes approach once,
  then asks you.
- **Risky workstreams plan first.** An engineer on shared or core code, or on
  work that is hard to undo, submits a plan for approval before editing.
- **Unclear bugs get rival hypotheses.** Isolated read-only investigators each
  test one hypothesis that makes a prediction, so the investigation does not
  anchor on the first plausible cause.

## Credits

The team techniques and other ideas this skill adopts are credited in
[CREDITS.md](CREDITS.md).
