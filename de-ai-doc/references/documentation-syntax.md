# Documentation Syntax — Preserve Markup, Edit Prose

Read this reference before editing comments or docstrings. It expands the
protected-content rules in [Editorial Rules](editorial-rules.md#safeguards);
the main rules' precedence and exceptions still apply.

Edit natural-language descriptions while preserving documentation delimiters,
structural markers, tags, attributes, identifiers, references, and code examples
character-for-character. Preserve their order and structural indentation. These
protections also apply to unlisted and custom tags. Examples include:

- **JSDoc:** `@param`, `@returns`, `@throws`, `@example`, `@deprecated`, `@see`,
  `@type`, and `@since`, including parameter names and type expressions.
- **Python docstring conventions:** Existing section headers such as `Args:`,
  `Returns:`, `Raises:`, `Notes:`, and `Examples:`, with their indentation.
- **PowerShell:** `.SYNOPSIS`, `.DESCRIPTION`, `.PARAMETER`, and `.EXAMPLE`,
  including parameter names.
- **reStructuredText:** Field markers such as `:param:`, `:type:`, `:returns:`,
  and `:raises:`, including associated names and types.
- **C# XML documentation:** Opening, closing, and self-closing tags such as
  `<summary>`, `<param>`, `<returns>`, `<exception>`, `<remarks>`, and `<example>`;
  attributes and their values, including `name`, `cref`, and `href`; inline
  references such as `<paramref name="timeout"/>`; and contents of `<c>` and
  `<code>` elements. Preserve XML nesting and existing escaping, and escape
  any reserved XML characters introduced by prose edits.
- **Rustdoc:** `///`, `//!`, and existing section headings such as `# Examples`,
  `# Panics`, and `# Safety`.

Preserve comment delimiters such as `///`, `/**`, `*/`, `*`, `#`, and `"""`.
Code and expected output within example sections remain unchanged; surrounding
explanatory prose may be edited.

For example, in `/// <param name="timeout">The timeout in seconds.</param>`,
the description may be edited while `///`, `<param name="timeout">`, and
`</param>` remain unchanged.
