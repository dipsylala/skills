# Editorial Rules

Use this checklist to correct unclear meaning, unsupported claims, repetition,
and inappropriate tone. Stylistic patterns do not establish AI authorship:
human writing can contain them, and generated writing can avoid them.

These defaults target English technical documentation. Adapt them to the
document's genre, audience, and language conventions.

## Safeguards

Apply these safeguards to every editing decision.

### Precedence

When rules compete, apply them in this order:

1. Follow the user's explicit instructions and requested scope.
2. Preserve factual accuracy, safety information, and source meaning.
3. Preserve literal regions and required syntax.
4. Follow repository conventions and established terminology.
5. Apply the relevant document-specific rules.
6. Apply general style heuristics.

A lower-priority improvement must not violate a higher-priority rule.

### Scope and Protected Content

Leave out-of-scope files, generated files, vendored dependencies, and build
output unchanged. Pure source code, configuration, logs, stack traces,
serialized data, and code-only inputs are not prose-editing targets. Edit source
comments or docstrings only when the request includes them.

Preserve these character-for-character unless the request requires a change:

- Fenced code blocks and language tags, inline code, commands, and output
- YAML or TOML frontmatter
- URLs, identifiers, paths, option names, environment variables, and versions
- Markdown link targets and anchors
- Documentation markup, delimiters, tags, attributes, and structural indentation
- Executable examples and text quoted from another source

Preserve required headings and hierarchy, factual table contents and cell
relationships, warnings, prerequisites, constraints, qualifications, and
attribution while allowing careful presentation edits. Keep deliberate
placeholders in templates, examples, and fill-in instructions. Report unfilled
placeholders elsewhere, such as "[Name]", "(Add your URL here)", or dates like
"2025-xx-xx", as gaps rather than inventing values.

If a file contains only protected content, leave it unchanged. Before editing
comments or docstrings, read [Documentation Syntax](documentation-syntax.md)
for the boundary between editable descriptions and protected markup.

### Meaning and Evidence

Grammar and style edits must preserve meaning. Make factual corrections or
additions only when supplied documents or repository context establish them
and the requested scope permits them. Add no facts merely to strengthen prose.

Verify consequential or inconsistent claims against the available sources
regardless of presumed authorship. When evidence is missing or conflicting,
preserve the original claim and report the uncertainty separately; do not
present it as verified or resolve ambiguity by guessing.

For each edited section, distinguish wording changes, compression, and removal
of padding from factual corrections. Report material factual corrections and
unresolved gaps separately from the edited document.

Preserve degrees of certainty, conditions, negations, and distinctions between
association, causation, participation, and leadership. Keep material limits on
evidence, dates, and source access that the sources establish; if their
significance is unclear, retain them and report the uncertainty. The Evidence
checks cover disclaimers the sources do not support.

### Context and Voice

A word, rhetorical shape, or formatting pattern alone never justifies an edit.
Identify its effect on meaning, comprehension, or tone before changing it.
Keep precise domain terms, useful transitions and summaries, necessary
politeness and accessibility language, and meaningful authorial voice.
Preserve effective literary devices, unusual rhythm, and deliberate repetition.

## Choose Editing Scope

Before editing, identify defects in clarity, specificity, repetition, structure,
or evidential support. Choose the smallest intervention that addresses them:

- **No change:** The passage is clear, relevant, and appropriately supported.
- **Sentence editing:** Local wording, grammar, or filler obscures the point.
- **Paragraph rewriting:** Repetition or unclear relationships prevent a
  paragraph from making its point.
- **Section restructuring:** Ordering or duplication across paragraphs prevents
  readers from following the explanation or completing the task.

Missing evidence calls for verification or a reported gap, not a larger rewrite.

## Prose Checks

### Clarity

- Prefer concrete nouns and verbs. Use active voice when the actor matters;
  passive voice can be clearer when the actor is unknown or irrelevant.
- Use plain verbs such as "is", "has", and "use" when they express the intended
  meaning. A formal synonym is not inherently more precise: keep "ask" when it
  is clear. Avoid renaming the same concept merely to vary the wording.
- Remove throat-clearing such as "it is worth noting" or "when it comes to"
  when it delays the point. Reduce stacked hedges such as "might possibly be
  able to" without removing necessary uncertainty.
- Use "to" for "in order to" and "because" for "due to the fact that" when the
  meaning is unchanged.
- Remove "simply" and "just" when they dismiss difficulty or hide prerequisites;
  keep meaningful uses such as "just before shutdown".
- Rewrite anthropomorphism when it obscures behavior, agency, or responsibility.
  Conventional shorthand such as "the function expects a nonempty string" or
  "the parser assumes UTF-8" can communicate a precise contract or assumption.
- Each paragraph should contribute information, reasoning, orientation, or a
  necessary transition. A concrete noun or named product is insufficient:
  "The Acme server represents an exciting future" explains nothing about it.
  Compress or delete content that provides no useful information or reading
  support.

#### Inspect Vocabulary in Context

Before changing a flagged term, apply this four-question test:

1. Does it name a precise domain concept?
2. Does the sentence identify the actor, action, object, or result?
3. Is the claim supported by a mechanism, measurement, example, or source?
4. Would a plainer alternative be more exact?

Keep precise, supported wording. Rewrite terms that substitute praise or
abstraction for information, such as "seamless" without an explained interaction
or "transformative" without a supported change. For additional examples when
examining repeated vague or inflated phrasing, consult the optional
[vocabulary reference](editorial-vocabulary.md).

#### Vague Connection Phrases

Inspect phrases such as "associated with", "connected to", and "in connection
with" when they obscure a relationship that the source establishes.

Replace an indirect relationship with a specific role or action only when the
supplied evidence establishes it. Otherwise preserve the relationship and flag
missing detail when it matters to the document.

**Examples:**

- **Rewrite when evidence supports specificity:** "She was associated with the
  project's leadership." If the source confirms she led it, rewrite as "She led
  the project."
- **Preserve when specificity is unsupported:** "She was associated with the
  project's leadership." If no role is established, retain the sentence and
  flag the missing role if it matters. This preserves the available meaning;
  it does not endorse vague wording as ideal prose.
- **Tighten without changing the claim:** "His work in connection with AI ethics
  has gained recognition." Rewrite as "His work on AI ethics has gained
  recognition." Preserve the recognition claim and any attribution; do not
  infer that the work was research.

### Evidence

Apply the factual-correction and unresolved-gap rules in Safeguards to these
checks:

- Replace vague benefits, significance, or impact with the mechanism, evidence,
  or narrower claim the sources support. Inspect claims about a "lasting
  legacy", a "pivotal moment", or transforming an industry.
- Replace unsupported superlatives such as "best" and "fastest" with an evidenced
  comparison. Remove empty praise; report unresolved substantive comparisons.
- Inspect appended interpretations introduced by "highlighting", "ensuring",
  "reflecting", or similar participles. Remove restatements that merely inflate
  the preceding fact, and separate observed behavior from inferred conclusions.
- Replace vague authorities such as "experts argue" or "critics say" with a named
  source or directly supportable statement when the evidence permits it. Check
  that citations support the attributed interpretation, not just a nearby fact.
- Preserve the extent of the evidence: one source is not a consensus, and an
  exhaustive list should not be introduced as examples with "such as". Describe
  coverage as independent, prominent, or high-quality only when relevant and
  established.
- Inspect disclaimers about evidence or usage: corrective framings such as
  "should be treated as X rather than Y", "does not by itself establish", or
  "should not be confused with", and claims that information is "not publicly
  available" or that a person "maintains a low profile". Keep a limit or
  distinction the sources establish. Report one they do not support as an
  unsupported claim; remove it only when it makes no claim about the subject,
  such as a framing that tells the reader how to treat a source.

### Repetition

- Remove duplication across prose, headings, signatures, and examples when it
  adds no reading support.
- Simplify mechanical sentence openers, forced three-item groups, and repeated
  "It does X. It also does Y" structures. Vary rhythm where it aids readability;
  repeating an established technical term can be clearest.
- Inspect repeated contrasts such as "not just X, but also Y", "not X, but Y",
  and "Y rather than X". Keep distinctions that clarify a real misconception;
  state both claims directly when a contrast is artificial or distracting.
- End a section when its explanation or argument is complete. Include a next
  action when the section supports a task.

### Tone

- Remove generic scene-setting, theatrical question-and-answer openings, and
  forced optimistic conclusions when they delay or obscure the point. Examples
  include "In today's fast-paced world", "Imagine a world", "Picture this",
  "Look no further", and "The future of X is here".
- Remove accidental assistant residue and engagement closers such as
  "Certainly", "I hope this helps", "Would you like me to", "Feel free to reach
  out", and "Don't hesitate to". Preserve them when quoted, instructional, or
  part of the document's subject. Apply the Evidence checks to disclaimers.
- Remove decorative emoji and avoid exclamation points in neutral technical
  documentation. Keep emoji with product meaning or explicitly requested use.
- Keep editor commentary out of the document unless requested, including
  unsolicited discussion of AI authorship or evading detection.

## Structure and Layout

Follow repository typography and markup conventions; preserve intentional
Unicode punctuation and symbols. Use punctuation to express relationships,
avoiding em dashes as a repeated all-purpose connector. Hold your own edits to
the same standard: introduce em dashes only where the document already uses
them, and keep a mix of sentence lengths and punctuation rather than reducing
every sentence to short comma-and-period clauses.

- Use sentence case for headings unless local conventions differ. Maintain
  heading hierarchy without skipped levels; normally reserve H1 for the title.
  Keep parent headings that group subtopics or aid navigation even without
  introductory prose.
- Remove excessive boldface and decorative thematic breaks when they add no
  useful hierarchy. Simplify "**Label:** description" bullets only when labels
  do not help scanning.
- Keep tables that support lookup, comparison, or scanning, including two-column
  label-and-value tables. Convert to prose or lists only when the replacement
  improves comprehension and preserves information and relationships. Check for
  needless duplication and unrelated entries forced into matching cells.
- Add summary sections such as "TL;DR" or "Key takeaways" only when the source
  already has one or the request asks for it.

## Document-Specific Checks

Apply the relevant checks in addition to the shared safeguards and prose checks.

### READMEs

- Lead with what the project does and who needs it.
- Make prerequisites, setup, and the shortest successful path easy to find.
- Remove generic mission statements that add no project information.

### Guides, API Documentation, and Procedures

- Organize around user tasks, with the shortest working path before advanced
  options. Use meaningful examples where available.
- State prerequisites and consequences before dependent steps or commands.
- Use imperative instructions, with one action per numbered step when order
  matters. Explain irreversible effects and how to validate the result.
- Name defaults, limits, side effects, permissions, and failure conditions where
  known; distinguish current behavior from plans and examples.

### Docstrings and Comments

- Start summaries with a direct verb where local conventions allow it. Remove
  preambles such as "This function" or "A helper that" when they add nothing.
- Explain value meaning, ranges, units, ordering, nullability, side effects,
  thread safety, exceptions, and non-obvious rationale rather than repeating
  parameter names or types as descriptions.
- Preserve deprecation replacements and reasons.

### Commit Messages

- Use an imperative subject, normally at most 50 characters, without a trailing
  period. Wrap body lines near 72 characters.
- Use the body to explain why the change was needed.

### Release Notes

- State the user-visible change and who it affects.
- Include migration steps and known limitations when relevant.

### Design and Decision Documents

- Keep rejected alternatives and tradeoffs.
- Attribute opinions and decisions to their owners when known.
- Separate decisions, assumptions, evidence, inferences, alternatives, and
  unresolved questions.

### Technical Articles

- Allow personality and narrative that serve the explanation.
- Avoid generic scene-setting and forced listicle structure.

## Final Pass

1. Compare technical claims with the original and available repository context;
   account for changes to identifiers, numbers, negations, and modal verbs.
2. Confirm protected content and required syntax are unchanged except for
   changes required by the request.
3. Search each file with a deterministic tool for zero-width characters,
   bidirectional controls, Unicode tag characters, and soft hyphens outside
   protected regions, and remove them. Replace unusual space characters and
   look-alike punctuation, such as U+02BC used as an apostrophe in English, with
   the document's usual characters. Keep characters the text needs: right-to-left
   scripts, letters such as U+02BC in languages that use it, deliberate
   non-breaking spaces, and intended hyphenation points.
   Report what you removed.
4. Check links, fences, frontmatter, tables, and structural markers, plus
   terminology and cross-references across all supplied files. Report links
   that carry AI-tool tracking parameters (`utm_source=chatgpt.com`,
   `utm_source=openai`, `utm_source=copilot.com`, `referrer=grok.com`) and stray
   `<mark>` highlighting, leaving them unchanged unless the request covers them.
5. Remove accidental formatting churn and check for repetitive rhythm, em dashes
   you introduced, uniformly short sentences, or abrupt over-editing.
6. Keep editorial notes separate from document content. Report material factual
   corrections and unresolved gaps, then stop when these checks succeed.
