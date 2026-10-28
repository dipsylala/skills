# Go

Language-specific signals for the rules in [SKILL.md](../SKILL.md). Rule numbers refer to its Rules section.

## Idiomatic, not a smell

- Repeated `if err != nil { return ... }` blocks are Go's error idiom, not spaghetti branching.
- Small interfaces with one production implementation, when unexported, defined by the consumer, and listing only the methods it calls.
- Producer-exported interfaces when the interface is the product (`io.Writer`, `hash.Hash32`).
- A type switch over a closed set in one package (for example, an AST walker).
- Driver or format registration via blank import (`database/sql`, `image`).

## Type and boundary escapes (rule 5)

- `interface{}` / `any` parameters and `map[string]any` carrying structured data → a struct, or generics (1.18+) when the type varies uniformly. Decoding genuinely unknown JSON is exempt.
- Single-value type assertions (`v := x.(T)`) outside proven invariants → the `v, ok :=` form, or a type that removes the assertion.
- `reflect` used for a fixed, known set of types → a type switch or generics.
- Errors discarded with `_` without a comment, or matched by string → `errors.Is` / `errors.As`. Wrap with `%w` only when callers need the cause; wrapping is an API commitment, and `%v` is right for hiding internals.
- In-band error values (`-1`, `""`, `nil` meaning failure) → return `(T, error)` or `(T, bool)`.
- `panic` used for ordinary control flow.
- A nil argument that silently selects different behaviour (nil config meaning "use globals") → an explicit option or a separate function.

## Branching and spaghetti (rule 2)

- Type switches over the same set of types in several packages → a method on a small interface.
- Boolean parameters that select behaviour → separate functions, or an options struct when there are several.

## Wrappers and magic (rule 4)

- Producer-side interfaces mirroring a single struct with no consumer that needs the abstraction.
- Functional options where plain parameters or an options struct would do: few settings, and most callers set them.
- `init()` side effects beyond registration, and package-level mutable globals.

## Canonical helpers (rule 6)

- Prefer the standard library (`slices`, `maps`, `cmp`, `strings`, `errors`, `context`, `sync`) over hand-written loops and helpers it already covers. `slices`, `maps`, and `sync.OnceValue` need Go 1.21+; check the `go` directive in `go.mod`.
- `util` / `common` / `helpers` packages accumulating unrelated functions → move each function to the package that owns its concept.

## Concurrency and atomicity (rule 7)

- Independent sequential I/O calls → `errgroup.WithContext` (`golang.org/x/sync`), or `sync.WaitGroup` when the calls return no errors, when that simplifies the orchestration.
- Functions that start goroutines internally where a synchronous API would do → stay synchronous and let the caller add concurrency.
- Goroutines with no owner: no `WaitGroup`, `errgroup`, or cancellation path.
- `context.Context` not propagated through calls that do I/O, or stored in a struct instead of passed as the first parameter.
- Maps or slices written concurrently without a mutex (`go test -race` catches these); channels used where a mutex is simpler.

## File size and decomposition (rule 1)

- Files within a package can be split without changing the API, so a file over 1000 lines is cheap to decompose; push for it.
- Generated files exempt from rule 1: files with a line matching `^// Code generated .* DO NOT EDIT\.$` before the first non-comment text.
