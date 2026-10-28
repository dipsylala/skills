# Rust

Language-specific signals for the rules in [SKILL.md](../SKILL.md). Rule numbers refer to its Rules section.

## Idiomatic, not a smell

- `unwrap()` / `expect()` in tests and examples, and `expect("why this holds")` on invariants the code has just established.
- Long `match` expressions over an enum the module owns, with no wildcard `_` arm; exhaustive matching is the point.
- Cloning `Rc` / `Arc`, which is cheap and shares ownership.
- Single-implementation traits that serve as a test seam, an extension trait, or a sealed trait.

## Type and boundary escapes (rule 5)

- `unwrap()` / `expect()` on fallible input in production paths → propagate with `?` or handle the error.
- `todo!()`, `unimplemented!()`, or `panic!` on recoverable production paths.
- Truncating integer `as` casts → `TryFrom` / `try_into`. Float-to-int `as` saturates silently, so check the range explicitly.
- `.clone()` added to satisfy the borrow checker where restructuring ownership would remove it.
- `unsafe` blocks without a `// SAFETY:` comment stating the invariant.
- Several `bool` / `Option` fields whose valid combinations are restricted → one enum.
- `String` or `Box<dyn Error>` errors in a library's public API → a dedicated error type (an enum, or a struct with a kind accessor) implementing `std::error::Error + Send + Sync`.
- `Box<dyn Any>` and downcasting for a known set of types → an enum.
- Bare `#[allow(clippy::...)]` → `#[expect(lint, reason = "...")]` (1.81+).

## Branching and spaghetti (rule 2)

- The same `match` on an enum repeated across modules → a method on the enum.
- Nested `if let` chains → a single `match`, `let ... else` (1.65+), or let chains (1.88+, edition 2024).
- Boolean parameters that select behaviour → an enum.

## Wrappers and magic (rule 4)

- `macro_rules!` where a function or generic would do.
- Traits with one implementation, no generic or `dyn` use, and no test double → inline the methods.
- `Deref` implemented to emulate inheritance → explicit methods, or `AsRef` / `Borrow`.
- Newtypes that add no invariant, type distinction, API restriction, or orphan-rule trait impl.

## Canonical helpers (rule 6)

- Prefer iterator adaptors, the `entry` API, and `?` over manual index loops, lookup-then-insert, and hand-written `match` on `Result`.
- Use crates the workspace already depends on before adding a near-duplicate.

## Concurrency and atomicity (rule 7)

- Independent sequential `.await`s → `join!` / `try_join!` (concurrent on one task) or a `JoinSet` / spawned tasks (parallel).
- Blocking calls (`std::fs`, `thread::sleep`, heavy CPU work) inside async code → `spawn_blocking` or the async equivalent.
- `std::sync` or `parking_lot` guards, or `RefCell` borrows, held across `.await` → shorten the critical section; use `tokio::sync::Mutex` only when the lock must span an await.
- `Arc<Mutex<_>>` spreading through APIs → a type with synchronous methods that owns the lock, or a task that owns the resource and receives messages.
- Spawned tasks whose `JoinHandle` is dropped and whose errors are lost.

## File size and decomposition (rule 1)

- A growing `lib.rs` or `mod.rs` → split into submodules.
- Generated files exempt from rule 1: code written to `OUT_DIR` by `build.rs` (including `prost-build` output), and checked-in copies of it.
