# Go

Language-specific signals for the rules in [SKILL.md](../SKILL.md). Rule numbers refer to its Rules section.

## Idiomatic, not a smell

- Repeated `if err != nil { return ... }` blocks are Go's error idiom, not spaghetti branching.
- Small interfaces defined at the consumer, with one production implementation, are idiomatic when they serve as a test seam.

## Type and boundary escapes (rule 5)

- `interface{}` / `any` parameters and `map[string]any` carrying structured data → a struct.
- Single-value type assertions (`v := x.(T)`) outside proven invariants → the `v, ok :=` form, or a type that removes the assertion.
- `reflect` used for a fixed, known set of types.
- Errors discarded with `_ =`, matched by string comparison, or wrapped without `%w` → `errors.Is` / `errors.As` on wrapped errors.
- `panic` used for ordinary control flow.
- `nil` pointers used as a hidden mode switch.

## Branching and spaghetti (rule 2)

- Type switches over the same set of types in several packages → a method on a small interface.
- Boolean parameters that select behaviour → separate functions, or an options struct when there are several.

## Wrappers and magic (rule 4)

- Producer-side interfaces mirroring a single struct with no consumer that needs the abstraction.
- Functional options for a constructor with one or two settings.
- `init()` side effects and package-level mutable globals.

## Canonical helpers (rule 6)

- Prefer the standard library (`slices`, `maps`, `strings`, `errors`, `context`, `sync`) over hand-written loops and helpers it already covers.
- `util` / `common` / `helpers` packages accumulating unrelated functions → move each function to the package that owns its concept.

## Concurrency and atomicity (rule 7)

- Independent sequential calls → `errgroup.Group` with a shared `context`.
- Goroutines with no owner: no `WaitGroup`, `errgroup`, or cancellation path.
- `context.Context` not propagated through calls that do I/O.
- Maps or slices shared across goroutines without a mutex; channels used where a mutex is simpler.

## File size and decomposition (rule 1)

- Files within a package can be split without changing the API, so a file over 1000 lines is cheap to decompose; push for it.
- Generated files exempt from rule 1: files marked `// Code generated ... DO NOT EDIT.`
