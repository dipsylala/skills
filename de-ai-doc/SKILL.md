---
name: de-ai-doc
description: Update one or more documentation files in place to replace AI-heavy writing with concise, natural, technically precise prose while preserving facts, code, structure, and author intent. Use when given paths to READMEs, API docs, guides, docstrings, comments, release notes, design docs, technical articles, or other documentation containing filler, hype, canned transitions, repetitive structure, vague claims, excessive hedging, decorative formatting, or other LLM writing patterns.
---

# De-AI Documentation

Update documentation in place by following the workflow below and the rules in
[editorial-rules.md](references/editorial-rules.md).

## Input

Accept one or more document paths from the user's invocation. Paths may name
individual files or directories.

- For a file, edit that file.
- For a directory, discover documentation files within it. Prefer Markdown,
  MDX, reStructuredText, AsciiDoc, and plain-text documentation. Include source
  files only when the request explicitly covers docstrings or comments.
- Respect explicit include or exclude instructions.
- Do not edit generated files, vendored dependencies, lockfiles, build output,
  or unrelated source files.
- If no path or document content is provided, ask for the documents to update.

## Execution

Perform the rewrite directly with the active agent. Do not call an external
LLM, model provider, rewriting API, or subprocess that submits the document to
another model. Use local tools only to inspect files, apply edits, format text,
or run deterministic validation. Do not fabricate facts, examples, or details
not present in the source documents or available repository context.

## Workflow

1. Resolve the supplied paths and list the documents in scope.
2. Read every in-scope document before editing. Identify its document type,
   intended reader, purpose, local style, and when editing multiple files,
   relationships between them.
3. Read [editorial-rules.md](references/editorial-rules.md).
4. Apply the reference's precedence, preservation, editorial, and
   document-specific rules to each file.
5. Edit each document in place without expanding beyond the requested scope.
6. Run the reference's final pass against each changed file and inspect the
   complete diff. Revise and repeat until the checks succeed. When a gap
   cannot be resolved from the supplied files or repository context, record
   it for the output report and move on rather than looping.

## Output

Update the supplied documents rather than returning replacement text for the
user to apply. Finish with a concise list of changed files and any unresolved
factual gaps. Do not include unchanged files or a long explanation of the
editing process.
