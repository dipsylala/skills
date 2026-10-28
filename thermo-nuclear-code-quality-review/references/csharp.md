# C\#

Language-specific signals for the rules in [SKILL.md](../SKILL.md). Rule numbers refer to its Rules section.

## Idiomatic, not a smell

- An `IFoo` / `Foo` pair is idiomatic when the interface is the dependency-injection or test seam. Flag it only when nothing consumes the interface.

## Type and boundary escapes (rule 5)

- `dynamic`, `object` parameters, and explicit casts `(T)x` where pattern matching or a precise type fits.
- The null-forgiving operator `!`, `#nullable disable`, and `#pragma warning disable` for nullability warnings.
- `Dictionary<string, object>` used as a data carrier → a `record`.
- Optional parameters that encode mutually exclusive modes.

## Branching and spaghetti (rule 2)

- `is` / `as` type-check chains → switch expressions with patterns, or polymorphism.
- The same `switch` on an enum in several places → one mapping or behaviour on a type.
- Boolean parameters that select behaviour → separate methods or an enum.

## Wrappers and magic (rule 4)

- Reflection or attribute-driven behaviour that hides control flow a direct call would show.
- Extension methods on broad types (`object`, `string`) that encode domain rules.
- Convention-based assembly scanning that makes dependency wiring impossible to trace.
- `partial` classes used to hide the size of a god class.

## Canonical helpers (rule 6)

- Prefer LINQ, BCL guard helpers (`ArgumentNullException.ThrowIfNull`), and existing project utilities over hand-rolled equivalents.

## Concurrency and atomicity (rule 7)

- `await` inside a `foreach` over independent work → `Task.WhenAll`.
- Sync-over-async (`.Result`, `.Wait()`, `GetAwaiter().GetResult()`).
- `async void` outside event handlers.
- `CancellationToken` accepted but not passed on.
- Several `SaveChanges` calls for one logical operation → one unit of work or transaction.

## File size and decomposition (rule 1)

- Several unrelated public types in one file.
- Generated files exempt from rule 1: `*.g.cs` and `*.Designer.cs`.
