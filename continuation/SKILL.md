---
name: continuation
description: Create compact continuation notes so another agent or future session can resume work with minimal rediscovery. Use when the user asks to resume later, checkpoint progress, compact the conversation, summarize current progress, prepare notes for a new session, or pass work to another agent.
argument-hint: "What should the next session focus on?"
---

Write a compact but specific continuation document for a fresh agent or future session.

The document must preserve only the context needed to continue the work. Prefer exact paths, commands, decisions, constraints, and unresolved questions over broad summaries.

Before writing, quickly establish the current state from available context and local workspace signals when relevant, such as the current directory, `git status`, changed files, and durable artifacts already mentioned in the conversation. Do not run expensive, destructive, or network-dependent commands just to create the continuation.

Save the document in the current workspace by default. If the workspace is a Git repository, prefer the repository root; otherwise use the current working directory. Use another location only if the user explicitly requests it. If there is no accessible workspace, provide the document content directly in the response instead. Use a clear filename such as `continuation-YYYYMMDD-HHMM.md`; if that filename already exists, add a short suffix instead of overwriting. Report the absolute path when saved.

If the user passed arguments, treat them as the expected focus of the next session and tailor the document around that focus.

Use concise headings from this list. Include only sections that help continuation; omit irrelevant empty sections instead of filling the document with `Unknown`.

- Current objective
- User intent, constraints, and preferences
- Important context and decisions
- Conversation state to preserve, including discarded approaches or superseded plans
- Repository/workspace state, including relevant paths
- Files changed, created, deleted, or intentionally left unchanged
- Commands/tools run and their outcomes
- Current implementation status
- Verification completed
- Verification still needed
- Blockers, risks, assumptions, or open questions
- Durable artifacts to read first, with paths or URLs
- Next recommended steps
- Suggested skills

For files changed or created, include the path, purpose of the change, and whether the change appears complete.

For commands/tools run, include the command or tool name, the working directory when relevant, the outcome, and any important errors. Do not include noisy logs unless they are needed for continuation.

Do not duplicate content already captured in durable artifacts such as PRDs, plans, ADRs, issues, commits, diffs, generated docs, or test reports. Reference those artifacts by path or URL and summarize only the continuation-critical point.

In "Suggested skills", list only skills that are known to exist in the current session or repository. Include a short reason for each. If none are clearly relevant, write `None`.

Clearly distinguish verified facts from assumptions or guesses. Mark stale or uncertain information explicitly.

Redact sensitive information including API keys, passwords, tokens, credentials, private URLs, personal data, and any other secrets. Preserve useful surrounding context and replace secrets with explicit placeholders such as `[REDACTED_TOKEN]`.

Do not invent repository state, file changes, commands, test results, skill availability, or paths. For continuation-critical facts that should exist but cannot be verified, write `Unknown`.

Before saving or responding, audit the document for:

- Contradictions: no conflicting status claims, such as both "tests passed" and "tests not run".
- Ambiguity: paths, commands, blockers, and next steps are specific enough for the next agent to act on.
- Persona consistency: the tone stays factual, concise, and continuation-oriented.
- Cognitive load: noisy logs and low-value recap are omitted; next steps are ordered by likely priority.
- Semantic coverage: the objective, current state, relevant changes, verification status, blockers, durable artifacts, and next action are covered when relevant.
