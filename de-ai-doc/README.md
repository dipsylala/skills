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
  shared safeguards, checks for clarity, evidence, repetition, and tone,
  document-specific guidance, and the final review.
- [`references/documentation-syntax.md`](references/documentation-syntax.md)
  defines protected syntax and editable prose for comments and docstrings.
- [`references/editorial-vocabulary.md`](references/editorial-vocabulary.md)
  supplies optional examples for investigating vague or inflated phrasing.

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

### DeSlop

The initial taxonomy of padding, cliché structures, protected regions, and
document-specific rules was adapted from
[AUAggy/deslop](https://github.com/AUAggy/deslop/), reviewed June 8, 2026. The
invisible-character check and additional padding, hype, and engagement phrases
follow its v0.1.6 and v0.1.7 releases, reviewed October 29, 2026.
DeSlop is available under the [MIT License](https://github.com/AUAggy/deslop/blob/main/LICENSE).
Copyright (c) Miaggy.com.

### Wikipedia

Patterns for inflated significance, superficial analyses, vague attributions,
vague connection phrases, corrective-framing disclaimers, placeholder residue,
AI-tool tracking parameters, and model-era vocabulary draw on
[Wikipedia:Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing),
reviewed October 29, 2026. Wikipedia text is available under the
[Creative Commons Attribution-ShareAlike 4.0 License](https://creativecommons.org/licenses/by-sa/4.0/).
