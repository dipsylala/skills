---
name: thermo-nuclear-code-quality-review
description: Extremely strict maintainability review of a branch's changes, reported as findings and a verdict without editing code.
disable-model-invocation: true
---

# Thermo-Nuclear Code Quality Review

Review the changes for structure and maintainability, then report findings and a verdict. Leave the code unchanged: every restructuring goes into the report as a proposal.

Review with a **code judo** stance: look for the restructuring that preserves behavior while making whole branches, helpers, modes, or layers disappear, so the change feels inevitable in hindsight. Push for the version that deletes complexity over one that rearranges it.

## Workflow

1. **Scope.** Use the target the user names (PR, branch, commit range, or paths). Otherwise review the current branch against its merge base with the default branch, plus uncommitted changes. Done when you can list every changed file.
2. **Languages.** List the languages in the changed files and read the matching reference for each:
   - TypeScript / JavaScript: [typescript.md](references/typescript.md)
   - Python: [python.md](references/python.md)
   - Go: [go.md](references/go.md)
   - Rust: [rust.md](references/rust.md)
   - Java / Kotlin: [java-kotlin.md](references/java-kotlin.md)
   - C#: [csharp.md](references/csharp.md)
   - C / C++: [c-cpp.md](references/c-cpp.md)

   For any other language, apply the rules by analogy to its type system, dispatch mechanisms, and concurrency model.
3. **File sizes.** Record each changed file's line count at the base and at the head. Rule 1 uses these numbers.
4. **Review.** Read every changed hunk with enough surrounding code to see the flow it joins, and check it against rules 0–7. Search the codebase for existing helpers and owning modules before calling code bespoke or misplaced. Done when every hunk has been checked against every rule.
5. **Report** in the format under [Output](#output).

## Rules

Each rule lists what to look for, the preferred remedy, an example comment, and its severity. A **blocker** fails the verdict unless the PR description, commit messages, or code comments give a clear structural justification. A **should-fix** is reported but does not fail the verdict.

### 0. Code judo — blocker

- **Look for:** a reframing that would delete whole categories of complexity; refactors that move code around without reducing the number of concepts a reader holds; a cleaner version of the same messy idea when a much simpler idea is visible.
- **Remedy:** delete a layer of indirection rather than polish it; reframe the state model so conditionals disappear instead of getting centralized; change the ownership boundary so the feature becomes a natural extension of an existing abstraction; turn special-case logic into a default flow with fewer exceptions.
- **Comment:** `i think there's a code-judo move here that makes this much simpler. can we reframe this so these branches disappear?` / `this refactor moves complexity around, but doesn't really delete it. is there a way to make the model itself simpler?`

### 1. File size — blocker

- **Look for:** a file at or under 1000 lines at the base that exceeds 1000 lines at the head. A file already over 1000 lines that the change grows further is a should-fix.
- **Exempt:** generated files; each language reference lists its markers. Review the generator input instead.
- **Remedy:** extract helpers, subcomponents, or modules so the file stays under 1000 lines. Accept the growth only for a compelling structural reason, with the resulting file still clearly organized.
- **Comment:** `this pushes the file past 1000 lines. can we decompose this first?`

### 2. Spaghetti growth — blocker

- **Look for:** new ad-hoc conditionals, scattered special cases, or one-off branches inserted into unrelated flows; one-off booleans, nullable modes, or flags threaded through existing control flow; narrow edge-case handling in an already busy function; "temporary" branching likely to become permanent; repeated conditionals that signal a missing model. Treat these as design problems even when the code works.
- **Remedy:** move the logic behind a dedicated abstraction, helper, state machine, policy object, or module; replace condition chains with a typed model or explicit dispatcher; collapse duplicate branches into one flow.
- **Comment:** `this adds another special-case branch into an already busy flow. can we move this behind its own abstraction?`

### 3. Structural regression — blocker

- **Look for:** working code that leaves a previously cohesive module more coupled, more stateful, or harder to scan; copy-pasted logic; refactors that pass tests but make the code less modular or less readable.
- **Remedy:** keep the behavior and restructure the implementation: extract a helper or pure function, separate orchestration from business logic, split a large file into focused modules.
- **Comment:** `this works, but it makes the surrounding code more spaghetti. let's keep the behavior and restructure the implementation.`

### 4. Direct, boring code — blocker

- **Look for:** brittle, ad-hoc, or "magic" behavior; generic mechanisms that hide simple data-shape assumptions; thin wrappers, identity abstractions, or pass-through helpers that add indirection without buying clarity.
- **Remedy:** delete the wrapper and keep the direct flow; replace the generic mechanism with code that states the data shape.
- **Comment:** `this abstraction seems unnecessary. can we just keep the direct flow?`

### 5. Explicit type boundaries — blocker

- **Look for:** unnecessary optionality; type-system escape hatches (top or dynamic types, unchecked casts, suppressed type errors); loosely-shaped ad-hoc objects; silent fallbacks that paper over an unclear invariant.
- **Remedy:** explicit typed models or shared contracts; make the boundary explicit so the control flow gets simpler.
- **Comment:** `why does this need a cast / optional here? can we make the boundary more explicit instead?`

### 6. Canonical layer and helpers — blocker

- **Look for:** feature logic leaking into shared paths; implementation details leaking through APIs; bespoke helpers where the codebase already has a canonical utility; logic in the wrong package, service, or layer.
- **Remedy:** reuse the canonical helper; move the logic to the module that already owns the concept; put feature-specific logic behind a dedicated abstraction.
- **Comment:** `this feels like feature logic leaking into a shared path. can we isolate it?` / `this looks like a bespoke helper for something we already have elsewhere. can we reuse the canonical one?`

### 7. Orchestration and atomicity — should-fix

- **Look for:** independent work serialized for no reason; related updates that can leave state half-applied. Flag orchestration that makes the implementation more brittle; leave micro-optimizations out.
- **Remedy:** run independent work concurrently when that also simplifies the orchestration; restructure related updates into an atomic flow.
- **Comment:** `these calls don't depend on each other. can we run them together and drop the sequencing?`

## Output

Report blockers first, then should-fix findings, each group ordered by how much complexity the proposal would remove. Report structural findings only: a few high-conviction findings beat a long list, and naming or formatting notes stay out.

For each finding:

- **Location:** `path:line`
- **Rule:** number and name
- **Severity:** blocker or should-fix, plus any justification found for a blocker
- **Problem:** what the change does to the structure
- **Proposal:** the restructuring, concrete enough to act on

Write direct, serious, demanding comments in the style of each rule's example. When a change makes the codebase messier or misses a dramatic simplification, say so plainly.

End with one verdict line:

- `Verdict: changes requested`, listing each unjustified blocker, or
- `Verdict: approve`, when no unjustified blocker remains. Should-fix findings may still stand.
