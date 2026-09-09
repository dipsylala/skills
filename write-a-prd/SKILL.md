---
name: write-a-prd
description: Create a product requirements document from user context, focused questions, and available repository evidence. Use when the user requests a PRD or asks to turn a feature plan into one.
---

# Write a PRD

## Process

1. Use the supplied context to identify the problem, intended users, desired outcomes, and requested destination. Ask only for missing information that materially affects the PRD.

2. Inspect relevant repository code and documentation when available to establish current behaviour and constraints. Distinguish verified behaviour, user reports, and proposed changes. If no repository is available, continue from the supplied context and mark unverified assumptions.

3. Ask focused questions about unresolved decisions that materially affect scope, outcomes, or acceptance. Resolve dependent decisions in order. Use answers already supplied; do not repeat an interview checklist. Establish observable acceptance conditions for each major story group. Draft when the material decisions are resolved or explicitly recorded as assumptions or open questions; identify any question that blocks implementation.

4. Record architectural decisions already made or needed to establish feasibility. Scale this work to the feature; leave other implementation choices open. Where module boundaries matter, favour cohesive functionality behind simple interfaces. Recommend testing based on observable behaviour, risk, and repository conventions. Ask the user about material tradeoffs that cannot be resolved from context.

5. Write the PRD using the template below, adapting the detail to the agreed scope. Check that each story has acceptance criteria, exclusions are clear, and assumptions are labelled. Record unknowns rather than inventing targets or decisions. Distinguish a draft with open questions from a PRD ready for implementation.

6. Produce the complete PRD in the requested destination, or in the response if none is specified. Publish it as a GitHub issue when the user has authorised publication and the target repository is known. Reuse existing authorisation; if it is missing and publication is desired, make the title and body reviewable before asking for it. If publication fails, retain the draft and report the failure. If the outcome is uncertain, check for an existing issue before retrying to avoid duplicates. Return the issue link after confirmed publication.

## PRD template

<prd-template>

## Problem Statement

The problem from the user's perspective, who experiences it, and the evidence or reports supporting it.

## Outcomes and Success Measures

The outcome the feature should produce and how it will be assessed. Include agreed measures and targets when known. Mark missing baselines or targets as open questions; distinguish product success from completion of the implementation.

## Solution

The solution to the problem, from the user's perspective.

## Scope and Priorities

The capabilities included in this release, their agreed priority, and any later phases. Do not present proposed priorities as agreed decisions.

## User Stories

A numbered list of distinct stories needed to cover the agreed scope, without padding. Give each story a stable identifier so acceptance criteria can refer to it. Use this format when it fits:

US-1. As an <actor>, I want a <feature>, so that <benefit>.

<user-story-example>
US-1. As a notes user, I want to search note titles and bodies, so that I can find relevant notes.
</user-story-example>

Group related stories under subheadings when that improves readability.

## Acceptance Criteria

A numbered list of observable, testable conditions that define when the feature is complete. Each criterion references one or more story identifiers and states enough detail for a developer to verify it. Cover relevant failure paths as well as successful use.

<acceptance-criteria-example>
AC-1 (US-1). Searching for a keyword returns notes accessible to the user where the title or body contains that keyword, case-insensitively.
AC-2 (US-1). A search with no matching notes displays an empty result state.
</acceptance-criteria-example>

## Constraints and Delivery

Where relevant, record accessibility, security, privacy, performance, compatibility, migration, rollout, and recovery requirements. Include known resource or timing constraints. State measurable conditions when agreed; omit irrelevant categories and label unresolved requirements.

## Implementation Decisions

A list of decisions already made or needed for feasibility, with their rationale. Separate proposals from confirmed decisions and leave unnecessary implementation choices open. This can include:

- The modules that will be built/modified
- The interfaces of those modules that will be modified
- Technical clarifications from the developer
- Architectural decisions
- Schema changes
- API contracts
- Specific interactions

Do NOT include specific file paths or code snippets. They may end up being outdated very quickly.

## Testing Decisions

A testing approach proportional to the feature's behaviour and risk. Distinguish recommendations from agreed decisions. Include relevant items:

- Observable behaviours and failure paths to verify, avoiding tests coupled to implementation details
- Appropriate test levels and any modules requiring isolated tests
- Existing test conventions or similar tests, when repository evidence is available

## Assumptions, Dependencies, and Open Questions

Assumptions requiring verification, dependencies on other work or systems, risks, and unresolved decisions. Identify which questions block implementation and how they can be resolved. Include owners only when known.

## Out of Scope

A description of the things that are out of scope for this PRD.

## Further Notes

Any further notes about the feature.

</prd-template>
