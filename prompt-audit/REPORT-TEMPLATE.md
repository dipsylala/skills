# Report Template

## Contradictions

List any instructions that directly conflict with each other. For each one:
- Quote both conflicting instructions exactly as they appear in the prompt.
- Label severity as ERROR or WARNING.
- Explain concretely why they conflict and what wrong behaviour a model would exhibit as a result.

If none found, write "No contradictions found."

## Ambiguity Issues

List any vague or underspecified instructions a model could interpret in multiple ways. For each one:
- Quote the ambiguous text exactly.
- State the type: Quantifier / Reference / Term / Scope / Other.
- Label severity as WARNING or INFO.
- Describe the multiple interpretations a model could take.
- Provide a concrete rewrite that removes the ambiguity.

If none found, write "No ambiguity issues found."

## Persona Issues

List any places where the expected tone, personality, or role contradicts itself. For each one:
- Describe exactly what is inconsistent.
- Name the two conflicting traits or tones.
- Quote the most relevant text from the prompt.
- Label severity as WARNING or INFO.
- Suggest how to make the persona consistent — pick one approach or reconcile them.

If none found, write "No persona issues found."

## Cognitive Load

State the overall complexity rating: Low / Medium / High / Very High.

Then list any instruction patterns that are hard for a model to follow. For each one:
- State the type: Nested Conditions / Priority Conflict / Deep Decision Tree / Constraint Overload.
- Describe what makes it hard to follow and what mistakes a model would likely make.
- Quote the relevant text from the prompt.
- Label severity as WARNING or INFO.
- Suggest how to restructure it (e.g. numbered steps, a table, split into separate prompts).

If none found, write "No cognitive load issues found."

## Semantic Coverage

State the overall coverage rating: Comprehensive / Adequate / Limited / Minimal.

### Coverage Gaps
List specific scenarios or user intents the prompt doesn't address, where the model would have to guess. For each one:
- Describe the gap.
- Quote the nearest relevant text from the prompt.
- Rate impact: High / Medium / Low.
- Provide exact text to add to the prompt to cover the gap.

### Missing Error Handling
List specific error conditions or edge cases the prompt doesn't handle. For each one:
- Describe the scenario.
- Quote the nearest relevant text from the prompt.
- Provide the exact instruction to add (e.g. "If the user provides X, respond with Y").
