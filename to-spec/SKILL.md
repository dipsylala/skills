---
name: to-spec
description: "Synthesize agreed decisions into a spec, save a local copy, and publish it to the project issue tracker."
disable-model-invocation: true
---

This skill records agreed decisions from the conversation, referenced sources, and codebase understanding. Do not reopen settled product or architectural decisions or start a new interview. The focused testing-boundary confirmation below is the only exception.

Resolve the issue tracker, local artifact location, and triage labels from the user's instructions and repository configuration. If no tracker is configured, use local files under `.scratch/<feature-slug>/`. Do not invent tracker labels. Use a remote tracker only when publishing there is authorized by the user's request or existing instructions.

## Process

1. Gather context. If given a path, issue number, or URL, read its full content and relevant comments. For a wayfinder map, follow its linked decision tickets; the map is an index, not the complete decision record. Report inaccessible or truncated sources instead of guessing their contents, and record any resulting gaps as unresolved questions.

2. Explore the repo to understand the relevant current behavior, if you haven't already. Use the project's domain glossary vocabulary throughout the spec, and respect ADRs in the area you're touching.

3. Establish testing boundaries. Reuse agreed testing boundaries. Otherwise, propose boundaries based on existing project practice and identify what each verifies. Request confirmation only when the choice requires a consequential decision. Keep unconfirmed proposals distinct from agreed decisions. Prefer existing public boundaries that verify the required behavior reliably. Add another boundary when an important invariant cannot be observed at the chosen boundary.

4. Write the spec using the template below. Distinguish agreed decisions, observed codebase facts, and unresolved questions. Do not present assumptions or proposals as decisions. A question blocks implementation when proceeding would require an implementer to invent a consequential decision. Record each blocker and the decision needed; nonblocking unknowns may remain documented without preventing completion.

5. Save the complete spec to `.scratch/<feature-slug>/spec.md`, following the configured local tracker convention if it specifies another location. Reuse an existing copy for this effort rather than overwriting an unrelated spec. Save it before publishing so tracker failures or truncation cannot lose the full draft.

6. Publish the spec as a planning parent using the configured tracker's convention. For a local tracker, the saved spec is the published artifact. If blockers remain, clearly mark the spec as a draft, use the configured draft or blocked state when available, and omit `ready-for-agent`. Otherwise, do not apply `ready-for-agent` unless the user explicitly intends the spec itself to be implemented as one work item. Resolve canonical label names through the configured triage vocabulary.

If publishing fails, preserve the complete local draft and report the failure. Before retrying an uncertain creation request, check whether the issue already exists; if that cannot be determined, report the uncertainty rather than creating a possible duplicate. On success, return the published identifier and link (or local path), the local copy's path, and any remaining blockers.

<spec-template>

## Problem Statement

The problem that the user is facing, from the user's perspective.

## Solution

The solution to the problem, from the user's perspective.

## User Stories

A numbered list of distinct, agreed outcomes. For features, use the familiar human-reviewable format:

1. As an <actor>, I want a <feature>, so that <benefit>

<user-story-example>
1. As a mobile bank customer, I want to see balance on my accounts, so that I can make better informed decisions about my spending
</user-story-example>

Cover relevant actors and failure cases already discussed. Do not invent requirements to fill the template. For refactors, migrations, or architectural work, replace this section with **Observable Outcomes and Invariants** rather than forcing user stories.

## Acceptance Criteria

Observable pass/fail conditions for the agreed outcomes, including agreed failure behavior and constraints. Do not invent requirements or include implementation steps.

## Implementation Decisions

A list of implementation decisions that were made. This can include:

- The modules that will be built/modified
- The interfaces of those modules that will be modified
- Technical clarifications from the developer
- Architectural decisions
- Schema changes
- API contracts
- Specific interactions

Describe implementation decisions using module names and contracts. Omit implementation paths and code, except compact prototype snippets needed to preserve an agreed decision precisely. Identify their prototype source and keep only the parts that encode the decision.

## Testing Decisions

A list of testing decisions that were made. Include:

- A description of what makes a good test (only test external behavior, not implementation details)
- The agreed public testing boundaries and the outcomes or invariants each verifies
- Prior art for the tests (i.e. similar types of tests in the codebase)

## Out of Scope

A description of the things that are out of scope for this spec.

## Further Notes

Any further notes about the feature.

## Unresolved Questions

List unresolved questions, identify which block implementation, and state the decision needed for each blocker. Write "None" when there are no unresolved questions.

## References

Link relevant ADRs, source issues, and decision tickets. References may contain paths; the restriction on implementation paths does not apply to source citations.

</spec-template>
