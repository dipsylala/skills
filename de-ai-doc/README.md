# De-AI Documentation

Rewrites AI-heavy documentation as clear, specific technical prose. The skill
preserves facts, code, markup, and author intent while removing filler, hype,
canned structures, vague claims, and other common AI-isms.

The skill uses the active agent directly. It does not send content to an
external LLM or rewriting service.

## Structure

- [`SKILL.md`](SKILL.md) defines the workflow: resolve the requested files,
  read them, apply the rules, edit them in place, inspect the diff, and report
  the result.
- [`references/editorial-rules.md`](references/editorial-rules.md) defines the
  rules: precedence, preservation, style checks, AI-ism patterns,
  document-specific guidance, and the final review.

Keeping workflow and editorial policy separate makes the skill easier to use
across agents without tying it to a provider or model.

## Usage

Invoke the skill with one or more files or directories:

```text
/de-ai-doc README.md
/de-ai-doc README.md docs/getting-started.md docs/reference/
/de-ai-doc docs/ --exclude docs/generated/
```

The skill reads the documents, edits them in place, checks the final diff, and
reports which files changed. When given a directory, it discovers documentation
files within that directory while avoiding generated files, dependencies,
build output, and unrelated source code.

## Scope

The skill supports READMEs, guides, API documentation, docstrings, comments,
commit messages, release notes, procedures, design documents, and technical
articles. It handles Markdown, MDX, reStructuredText, AsciiDoc, and plain-text
documentation by default.

Source files are included only when the request explicitly covers docstrings
or comments. The skill preserves literal regions such as code, commands,
identifiers, frontmatter, link targets, and executable examples. It does not
invent missing facts. When a rewrite exposes a factual gap that cannot be
resolved from the supplied files or repository context, the skill reports it.

## Sources

### Wikipedia: Signs of AI writing

[Wikipedia:Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)
is used as a field guide to common AI-isms. Its examples inform checks for:

- Inflated claims about significance, legacy, and broader trends
- Superficial analysis appended to otherwise factual statements
- Vague attribution and unsupported claims of consensus
- Negative parallelism and forced groups of three
- Avoidance of plain verbs such as "is", "are", and "has"
- Unnecessary synonym changes for the same subject
- Formulaic headings, lists, boldface, tables, and punctuation
- Leaked chatbot language, response scaffolding, and accidental placeholders

These patterns demonstrate recurring traits of generated prose. They are
editing signals, not proof that a particular passage was written by AI. The
skill fixes the underlying clarity, evidence, structure, or tone problem
instead of trying to conceal authorship.

The page was reviewed on June 8, 2026. Wikipedia text is available under the
[Creative Commons Attribution-ShareAlike License](https://creativecommons.org/licenses/by-sa/4.0/).

### DeSlop

The initial taxonomy of padding, cliché structures, protected regions, and
document-specific rules was adapted from
[AUAggy/deslop](https://github.com/AUAggy/deslop/), reviewed June 8, 2026.
DeSlop is available under the MIT License.
