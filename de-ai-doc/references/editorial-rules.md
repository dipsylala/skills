# Editorial Rules

Use this reference as a diagnostic checklist. Do not apply it as a blind word
filter: technical context can make an otherwise overused term precise.

The patterns below are descriptive signals, not proof that text was generated
by AI. Human writing can contain them, and AI-written text can avoid them.
Correct the underlying problem: weak sourcing, vague meaning, unsupported
analysis, poor structure, or inappropriate tone.

## Rule Precedence

When rules compete, apply them in this order:

1. Follow the user's explicit instructions and requested scope.
2. Preserve factual accuracy, safety information, and source meaning.
3. Preserve literal regions and required syntax.
4. Follow repository conventions and the document's established terminology.
5. Apply the relevant document-specific rules.
6. Apply general style and AI-ism heuristics.

Do not make a lower-priority stylistic improvement that violates a
higher-priority rule.

## Core Editing Principles

- Prefer concrete nouns and verbs over abstractions.
- Delete sentences that do not change what the reader knows or does.
- Replace vague benefits with mechanisms, evidence, or narrower claims.
- Use active voice when the actor matters; do not force it when the actor is
  unknown or irrelevant.
- Use direct instructions for procedures.
- Vary sentence and paragraph length naturally.
- Keep accurate domain terms. A flagged word is evidence to inspect, not an
  automatic deletion.
- Treat AI-writing patterns as diagnostic clues, not proof of authorship. Fix
  the underlying weakness rather than disguising a stylistic signal.
- Preserve necessary warnings, qualifications, politeness, accessibility
  language, and meaningful authorial voice. Concision does not outrank safety
  or accuracy.
- Rewrite at the smallest useful scope. Keep correct, specific prose instead of
  replacing every sentence.

## Preserve First

Preserve these character-for-character unless the request requires a change:

- Fenced code blocks, language tags, inline code, commands, and output
- YAML or TOML frontmatter
- URLs, identifiers, paths, option names, environment variables, and versions
- Markdown link targets and anchors
- Docstring markers, comment delimiters, indentation, JSDoc tags, reStructured
  Text fields, PowerShell help keywords, and C# XML documentation tags
- Executable examples and text quoted from another source

Preserve these semantically while allowing careful presentation edits:

- Required headings and their hierarchy
- Factual table contents and relationships between cells
- Warnings, prerequisites, constraints, qualifications, and attribution

Reformat or replace a table only when doing so improves comprehension without
losing information or relationships.

If a file contains only protected content, leave the file unchanged.

## Remove Padding

Delete throat-clearing that delays the point, including phrases such as:

- "it is worth noting", "it is important to note", and "needless to say"
- "basically", "essentially", "in fact", and "actually" when they add no
  contrast or correction
- "when it comes to", "in terms of", and "with that said"
- "without further ado", "as you may know", and "as previously mentioned"
- "feel free to", "do not hesitate to", and announcements of excitement
- "at the end of the day", "for all intents and purposes", and similar filler

Reduce stacked hedges such as "might possibly be able to." Keep uncertainty
when evidence is incomplete, behavior is conditional, or a guarantee would be
false.

Avoid "simply" and "just"; they conceal prerequisites and failure cases.

## Inspect AI-Favored Vocabulary

Replace these when they are vague, inflated, or used as generic praise:

- delve, unpack, deep dive, journey, realm, tapestry
- leverage, utilize, facilitate, empower, enable
- robust, seamless, holistic, dynamic, agile, scalable
- innovative, groundbreaking, transformative, disruptive, cutting-edge
- ecosystem, synergy, paradigm shift, thought leadership
- harness, unlock, unleash, supercharge, elevate, amplify
- orchestrate, curate, cultivate, foster, champion, catalyze
- reimagine, reinvent, redefine, reshape, revolutionize
- granular, intricate, pivotal, seminal, myriad, plethora
- mission-critical, best-in-class, world-class, industry-leading
- next-generation, future-proof, end-to-end, value-add
- north star, move the needle, low-hanging fruit, boil the ocean
- circle back, double-click, bandwidth, learnings, and "ask" as a noun

Before changing a flagged term, check:

1. Does it name a precise domain concept?
2. Does the sentence identify the actor, action, object, or result?
3. Is the claim supported by a mechanism, measurement, example, or source?
4. Would a plainer alternative be more exact?

Keep the term when it is precise and supported. Rewrite it when it substitutes
tone or abstraction for information.

Also inspect these terms and phrase families:

- **Inflated narrative:** a journey of, embark on a journey, embark on a
  voyage, a testament to, a multitude of, a plethora of, in a sea of,
  kaleidoscope, treasure trove, golden ticket, epicenter, linchpin, the next
  frontier, the road ahead, uncharted waters, new heights, reaching new
  heights, on the ascent to, from inception to execution
- **Grandiose praise:** adept, captivating, commendable, exemplary,
  enlightening, esteemed, exciting, flourishing, impactful, invaluable,
  profound, remarkable, relentless, thought-provoking, unparalleled, vibrant,
  well-crafted, undeniable, undoubtedly, utmost
- **Inflated importance:** cannot be overstated, crucial, paramount,
  fundamental, vital, notable, significant, considerable, substantial, key
  takeaways, growing recognition, widely recognized, strong presence,
  demonstrates significant, significantly contributes
- **Vague complexity:** arduous, complexity, deep understanding, delve into the
  intricacies of, manifold, multifaceted, nuanced, pervasive, systemic,
  entrenched, encountered hurdles, insights into, understanding of your unique
- **Vague action claims:** align, augment, conceptualize, craft, drive,
  enhance, enrich, explore, glean, grasp, maximize, optimize, promote,
  resonate, shed light, showcase, streamline, strive, tailor, thrive, and
  transform when they omit the actor, mechanism, object, or measurable result
- **Marketing compounds:** AI-powered, blockchain-enabled, cloud-based,
  customer-centric, data-driven, driven approach, ever-evolving,
  rapidly evolving, transforming the way, on the cutting edge, disruptive
  innovation, driving innovation
- **Corporate abstractions:** actionable insights, ample opportunities, brand
  awareness, capacity building, change management, collaborative environment,
  competitive landscape, continuous improvement, digital transformation,
  domain expertise, emerging technologies, ethical considerations, fresh
  perspectives, governance framework, implementation strategy, industry best
  practices, knowledge transfer, operational excellence, pain point, solution
  development, strategic alignment, subject matter experts, value proposition,
  value-added
- **Optimization abstractions:** cost optimization, operational efficiency,
  performance optimization, process optimization, resource allocation,
  resource optimization, risk mitigation, time optimization
- **Generic business outcomes:** adoption rate, customer loyalty, customer
  satisfaction, efficiency, market penetration, market share, profitability,
  revenue growth, sustainability, user engagement, user experience
- **Canned framing:** as such, broadly speaking, generally speaking, going
  forward, in brief, in conclusion, in essence, in general, in summary, moving
  forward, specifically speaking, that being said, ultimately, and whilst it
  is true when they announce structure without adding meaning
- **Meta-discourse padding:** to clarify, to elucidate, to emphasize, to
  exemplify, to highlight, to illustrate, to reiterate, to shed light on, to
  showcase, to summarize, and to underscore when they narrate the act of
  writing rather than state the point directly
- **Chatbot scaffolding:** based on the information provided, "certainly, here
  are", "certainly, here is", important to consider, it is important to
  remember, and it is worth noting that when they are response preambles rather
  than substantive warnings

Treat inflections and close variants as the same signal: `delve`, `delved`,
and `delving`; `embark` and `embarked`; `foster` and `fostering`; `enhance` and
`enhancing`; `transform` and `transformation`.

Use the ordinary verb when it is more exact: "use" for "utilize", "share" for
"socialize", "request" for "ask", and "raise" for "surface". Keep a term when
it has established domain meaning, such as scalability, an ecosystem API, an
Agile process, or end-to-end encryption.

Do not flag necessary technical or organizational terms merely because they
appear in an AI-ism list. Terms such as latency, downtime, uptime, throughput,
SLA, KPI, ROI, TCO, MVP, proof of concept, Scrum, sprint, onboarding,
offboarding, roadmap, stakeholders, deliverables, quality assurance, quality
control, regulatory compliance, root cause analysis, user interface, user
feedback, and deployment plan may be exact. Edit them only when they are
undefined, inaccurate, repetitive, or used as empty business jargon.

Common connective language is also neutral when it expresses a real
relationship. Do not remove "accordingly", "as a result", "consequently", "for
example", "for instance", "furthermore", "given that", "however", "moreover",
"nevertheless", "therefore", or similar transitions solely because they
appear frequently in generated text. Remove them only when they are repetitive,
mechanical, or unnecessary.

Reject unsubstantiated superlatives such as "best", "fastest", "easiest", and
"most powerful". Replace them with evidence or remove the comparison.

## Remove Generic Significance

LLM prose often replaces specific facts with broad claims about importance,
legacy, impact, or wider trends. Inspect phrases such as:

- "serves as a testament", "stands as a reminder", or "marks a pivotal moment"
- "underscores its importance", "highlights its significance", or "reflects
  the broader landscape"
- "lasting legacy", "indelible mark", "key turning point", or "setting the
  stage"
- Generic claims that a feature transforms an industry, shapes the future, or
  contributes to a larger movement

Keep significance only when it is relevant, specific, and supported. Prefer
the fact that establishes importance over an assertion that importance exists.
When a claim could go either way, apply the four-question test in
"Inspect AI-Favored Vocabulary".

## Remove Superficial Analysis

Check sentence-ending participial phrases such as "highlighting",
"underscoring", "ensuring", "reflecting", and "contributing". They often append
an interpretation that the source facts do not support.

- Delete analysis that restates the preceding fact in grander terms.
- Do not invent symbolism, influence, debate, recognition, or social impact.
- Attribute interpretations to a named source when they are genuinely sourced.
- Separate observed behavior from conclusions inferred from it.
- Apply the four-question test in "Inspect AI-Favored Vocabulary" when
  deciding whether an interpretation is supported by the source facts.

## Tighten Attribution

Replace vague authorities such as "experts argue", "observers note",
"industry reports suggest", and "critics say" with a named source or a
directly supportable statement.

- Do not turn one source into "many", "widely", "several", or a consensus.
- Do not label coverage independent, prominent, substantial, or high-quality
  unless that classification matters and can be established.
- Do not imply that a short list is representative with "such as" when it is
  actually exhaustive.
- Verify that citations support the interpretation attributed to them, not
  only a nearby factual detail.

## Break Canned Structures

Rewrite formats strongly associated with generic generated prose:

- A rhetorical question immediately answered by the author
- "This is not X. It is Y."
- "In a world where..." or "Imagine a world..."
- "Here is the thing", "Let us face it", or "The truth is"
- "At its core" and "Say goodbye to X and hello to Y"
- "Whether you are a beginner or an expert..."
- "In today's fast-paced world" or "digital landscape"
- "The future of X is here"
- "Despite these challenges" followed by a vague optimistic future outlook
- Repeated "not only X, but also Y" or "not X, but Y" constructions
- Forced groups of three adjectives, examples, clauses, or abstract nouns
- A sequence of bullets with identical grammatical openings
- Anthropomorphism: code or tools described as wanting, loving, knowing, or
  deciding; in technical prose, also check "the function expects", "the parser
  assumes", "the system thinks", and "the code believes"

Do not remove a rhetorical device merely because it matches a shape. Remove it
when it is predictable, theatrical, or less clear than a direct statement.

## Prefer Plain Grammar

- Use "is", "are", and "has" when they are clearest. Do not replace them
  reflexively with "serves as", "stands as", "represents", "boasts",
  "features", or "offers".
- Repeat an established technical term when it remains the clearest term.
  Avoid elegant variation that renames the same thing and creates ambiguity.
- Do not force every sentence into a different shape merely to avoid
  repetition. Vary rhythm where it helps readability.

## Control Tone and Typography

- Remove decorative emoji used as headings, bullets, hype, or emphasis.
- Preserve emoji when it carries product meaning or the user requests it.
- Avoid exclamation points in neutral technical documentation.
- Use the repository's existing typography. Do not silently normalize Unicode
  when curly quotes, dashes, or symbols are intentional.
- Avoid em dashes as a repeated all-purpose connector. Use punctuation that
  expresses the actual relationship.
- Avoid excessive boldface, title-cased subheadings, thematic breaks, and
  tables that add visual hierarchy without improving comprehension.
- Convert repetitive bullets of the form "**Label:** description" to prose,
  a real definition list, or a simpler list when labels do not aid scanning.
- Preserve heading levels and repository-native markup conventions.
- Do not add unsolicited editor commentary about being an AI, whether the text
  was AI-generated, or evading AI detection. Preserve such discussion when it
  is part of the document's subject.
- Remove leaked chatbot correspondence such as "Certainly", "You are
  absolutely right", "I hope this helps", "Would you like me to", and "let me
  know if you need anything else" when it is accidental response residue, not
  quoted or instructional content.
- Remove accidental response scaffolding, knowledge-cutoff disclaimers, and
  speculation about unavailable sources. Preserve deliberate placeholders in
  templates, examples, configuration samples, and fill-in instructions.

## Improve Technical Value

De-AI editing is more than style cleanup. Check whether the document:

- Answers what the feature does, who needs it, and when to use it
- States prerequisites before steps that depend on them
- Gives the shortest working path before advanced options
- Names defaults, limits, side effects, permissions, and failure conditions
- Distinguishes current behavior from plans or examples
- Uses one term for each concept
- Connects claims to mechanisms, measurements, or sources
- Includes meaningful examples rather than placeholder scenarios
- Removes duplication between prose, headings, function or API signatures, and examples
- Ends sections with a useful next action rather than a generic conclusion

Do not fabricate missing details. Mark consequential gaps for the author when
they cannot be resolved from the surrounding source.

## Document-Specific Checks

Apply the relevant document type in addition to the general rules.

### READMEs

- Lead with what the project does and who it is for.
- Make prerequisites, setup, and the shortest successful path easy to find.
- Remove mission statements and unsupported superiority claims.

### Guides and API Documentation

- Organize around user tasks.
- State prerequisites and consequences before commands.
- Keep terminology consistent.
- Name defaults, constraints, side effects, and failure conditions where known.

### Docstrings and Comments

- Preserve syntax, indentation, tags, and executable examples.
- Start summaries with a direct verb where local conventions allow it.
- Remove "This function", "A helper that", "Handles the logic for", "Allows
  you to", and similar preambles.
- Do not repeat parameter names or types as descriptions.
- Explain value meaning, valid ranges, units, ordering, nullability, side
  effects, thread safety, exceptions, and non-obvious rationale.
- Preserve deprecation replacements and reasons.

### Commit Messages

- Use an imperative subject, normally at most 50 characters.
- Do not add a trailing period to the subject.
- Wrap body lines near 72 characters.
- Use the body to explain why the change was needed.

### Release Notes

- State the user-visible change and who it affects.
- Include migration steps and known limitations when relevant.
- Avoid launch language and unsupported claims.

### Procedures

- Use imperative steps.
- Put one action in each numbered step when order matters.
- Explain irreversible effects and validation steps.

### Design and Decision Documents

- Do not convert uncertainty into certainty.
- Keep rejected alternatives and tradeoffs.
- Attribute opinions and decisions to their owners when known.
- Separate evidence from inference.
- Separate decisions, assumptions, alternatives, and unresolved questions.

### Technical Articles

- Allow personality and narrative when they carry information.
- Avoid generic scene-setting and forced listicle structure.
- Preserve sourced interpretation and distinguish it from observed fact.

## Final Pass

1. Compare every technical claim with the original document and available
   repository context.
2. Search for changed identifiers, numbers, negations, and modal verbs.
3. Confirm literal regions and required syntax are unchanged.
4. Check links, code fences, frontmatter, tables, and structural markers.
5. Check terminology and cross-references across all supplied files.
6. Remove accidental formatting churn.
7. Read aloud for repetitive rhythm and abrupt over-editing.
8. Remove editor commentary unless the user requested it.
