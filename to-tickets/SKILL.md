---
name: to-tickets
description: Break a plan, spec, or the current conversation into a set of tracer-bullet tickets, each declaring its blocking edges, published to the configured tracker (edges as text in one file per ticket locally, or native blocking links on a real tracker).
disable-model-invocation: true
---

# To Tickets

Break a plan, spec, or conversation into a set of **tickets**: tracer-bullet vertical slices, each declaring the tickets that **block** it.

Resolve the issue tracker, local artifact location, and triage labels from the user's instructions and repository configuration. If no tracker is configured, use local files under `.scratch/<feature-slug>/`, reusing the source spec's folder when working from a local spec. Do not invent tracker labels. Use a remote tracker only when publishing there is authorized by the user's request or existing instructions.

## Process

### 1. Gather context

Work from whatever is already in the conversation context. If the user passes a reference (a spec path, an issue number or URL) as an argument, fetch it and read its full body and comments.

Report inaccessible or truncated sources and identify any decisions that block implementation. Keep affected tickets as drafts with the decision needed; do not mark them ready for an agent to implement.

`ready-for-agent` means the ticket is sufficiently specified for implementation. Work can start only when its listed prerequisites are complete. Decisions that block implementation keep the ticket in draft.

### 2. Explore the codebase (optional)

If you have not already explored the codebase, do so to understand the current state of the code. Ticket titles and descriptions should use the project's domain glossary vocabulary, and respect ADRs in the area you're touching.

Look for opportunities to prefactor the code to make the implementation easier. "Make the change easy, then make the easy change."

### 3. Draft vertical slices

Break the work into **tracer bullet** tickets.

<vertical-slice-rules>

- Each slice cuts a narrow but complete path through the layers needed for its outcome, including applicable tests. Do not add schema, API, or UI work when the outcome does not need it.
- A completed slice is demoable or verifiable on its own
- Each slice is sized to fit in a single fresh context window
- Any prefactoring should be done first

</vertical-slice-rules>

Give each ticket its **blocking edges**: the other tickets that must complete before it can start. A ticket with no blockers can start immediately.

Before presenting the breakdown, verify that the dependency graph has no cycles, every blocker identifies a ticket or explicit external prerequisite, and every agreed outcome is covered by acceptance criteria.

**Wide refactors are the exception to vertical slicing.** A **wide refactor** is one mechanical change (rename a column, retype a shared symbol) whose **blast radius** fans across the whole codebase, so a single edit breaks thousands of call sites at once and no vertical slice can land green. Don't force it into a tracer bullet; sequence it as **expand–contract**. First expand: add the new form beside the old so nothing breaks. Then migrate the call sites over in batches sized by blast radius (per package, per directory), each batch its own ticket blocked by the expand, keeping CI green batch to batch because the old form still exists. Finally contract: delete the old form once no caller remains, in a ticket blocked by every migrate batch. When even the batches can't stay green alone, keep the sequence but let them share an integration branch that all block a final integrate-and-verify ticket; green is promised only there.

### 4. Quiz the user

Present the proposed breakdown as a numbered list. For each ticket, show:

- **Title**: short descriptive name
- **Blocked by**: which other tickets (if any) must complete first
- **What it delivers**: the end-to-end behaviour this ticket makes work
- **Acceptance criteria**: observable conditions that establish completion
- **Unresolved decisions**: remaining decisions, their implementation impact, and whether they prevent the ticket from being ready; write "None" when there are none

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the blocking edges correct: does each ticket only depend on tickets that genuinely gate it?
- Should any tickets be merged or split further?

Iterate until the user approves the breakdown.

### 5. Publish the tickets to the configured tracker

Publish the approved tickets using the resolved tracker or local artifact convention:

- **Local files** → before writing, inspect existing files for this effort. Reuse matching tickets, preserve unrelated files, and retain existing identifiers when revising the breakdown. Assign new identifiers to new tickets. Write one file per ticket under `.scratch/<feature-slug>/issues/<NN>-<slug>.md`. For an initial breakdown, number from `01` in dependency order (blockers first); for revisions, retain identifiers and express dependency order through "Blocked by". Each file's "Blocked by" lists the numbers/titles it depends on. Use the per-ticket file template below: one ticket per file, never a single combined file.
- **A real issue tracker (GitHub, Linear, …)** → publish one issue per ticket in dependency order (blockers first) so each ticket's blocking edges can reference real identifiers. Use the platform's native blocking relationship where it has one; otherwise set each ticket's "Blocked by" to the blocking issues. If the source was an existing issue, make each ticket its sub-issue when supported, otherwise link the parent in the child body. Apply the configured equivalent of `ready-for-agent` only to sufficiently specified tickets without decisions that block implementation, unless instructed otherwise.

Preserve complete local drafts before remote publication. If publication partially fails, report the created identifiers and remaining drafts. Before retrying an uncertain creation, check whether the issue already exists; if that cannot be determined, report the uncertainty rather than risking a duplicate. Return all created identifiers or local paths and any unresolved blockers.

Identify which tickets can start immediately. This skill ends after publishing tickets and reporting their identifiers or paths.

Leave the parent issue's body, state, and labels unchanged; linking tickets to it as sub-issues is the only change.

<local-ticket-template>

# <NN>: <Ticket title>

**What to build:** the end-to-end behaviour this ticket makes work, from the user's perspective, not a layer-by-layer implementation list.

**Blocked by:** the numbers/titles of the tickets that gate this one, or "None (can start immediately)".

**Spec:** the path to the source spec, when the breakdown came from one; otherwise omit this line.

**Status:** <ready-for-agent or draft; use draft when decisions block implementation>

- [ ] Acceptance criterion 1
- [ ] Acceptance criterion 2

</local-ticket-template>

<issue-template>

## Parent

A reference to the parent issue on the tracker (if the source was an existing issue, otherwise omit this section).

## What to build

The end-to-end behaviour this ticket makes work, from the user's perspective, not layer-by-layer implementation.

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2

## Blocked by

- A reference to each blocking ticket, or "None (can start immediately)". Omit this section when blockers were set as native edges.

</issue-template>

In either form, avoid implementation file paths or code snippets: they go stale fast. Source links, such as the spec path or parent issue, are exempt. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it and note briefly that it came from a prototype. Trim to the decision-rich parts, not a working demo, just the important bits.
