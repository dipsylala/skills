---
name: pr
description: "Use when writing a PR body."
metadata:
  credits:
    skill: show-me
    author: Dex Horthy
    organisation: Humanlayer
    url: "https://github.com/humanlayer/skills/blob/main/plugins/show-me/skills/show-me/SKILL.md"
---

Before drafting, inspect the complete proposed diff, relevant surrounding code, the repository's PR template, and available validation results. Describe only changes and evidence supported by those sources. State any material inspection limits.

Use this template for writing the PR body:

```markdown
## Summary

<problem and resulting behaviour; optional supporting visual>

## Evidence

- **Before:** <screenshot/output/failing test run>
  **After:** <screenshot/output/passing test run>

## Merge Danger

**Door:** <one-way or two-way>

<optional: description>

**Blast Radius:** <one-word description>

<optional: potential ramifications of merge>
```

## Sections

Skip all preambles and keep prose brief. Use the user's domain language from `GLOSSARY.md` when available, otherwise use terms from the repository and conversation. Follow the repository's PR template when required, incorporating this guidance into its matching sections.

### Summary

Lead with the problem and resulting behaviour. Add a visual when it materially helps a reviewer understand the change.

When a visual is useful, read [VISUAL-EXAMPLES.md](VISUAL-EXAMPLES.md) for examples and placement guidance.

### Evidence

Concrete evidence that the change works. Show a before and after.

Use only observed evidence. If before evidence was not captured or checks could not run, state that limitation. For documentation or other changes without a meaningful execution comparison, report the relevant inspection instead. Never invent screenshots, output, or test results.

Screenshots are S-tier - when the environment is set up for it and the change is visual.

Execution-based evidence is A-tier. Test results, console output. Show the exact test that now fails and passes, using pseudocode.

### Merge Danger

Describe whether it's a one-way or two-way door. You can walk back through two-way doors, but not one-way doors. A PR that is cheap to roll back is lower risk. Changes that involve destructive actions or hard-to-reverse decisions are one-way doors.

The blast radius is the potential impact or scope of the changes introduced by this PR. Consider all possibilities. Examples are layout shift, breakages for consumers, mobile responsiveness, etc.
