# C / C++

Language-specific signals for the rules in [SKILL.md](../SKILL.md). Rule numbers refer to its Rules section.

## Idiomatic, not a smell

- C: a single `goto cleanup` path for releasing resources on error.
- Long `switch` statements over an enum the module owns, with every case handled.

## Type and boundary escapes (rule 5)

- `void*` parameters and C-style casts where a typed interface fits.
- C++: `reinterpret_cast`, and `const_cast` used to drop `const`.
- C++: raw owning pointers → `std::unique_ptr` / `std::shared_ptr`.
- Out-parameters plus a `bool` or sentinel return → `std::optional` / `std::expected` (C++), or a result struct (C).
- Macros used as constants or functions → `constexpr` / `inline` (C++), `enum` or `static inline` (C).
- `int` flags encoding modes → an `enum` (`enum class` in C++); untagged unions → a tagged union or `std::variant`.

## Branching and spaghetti (rule 2)

- `#ifdef` platform or feature checks spread through shared code → isolate them behind a platform layer.
- The same switch on a type tag in several places → virtual dispatch, or `std::variant` with `std::visit`.

## Wrappers and magic (rule 4)

- Macro-built DSLs, and template metaprogramming or CRTP where a plain function or overload would do.
- Deep inheritance hierarchies used for code sharing → composition.

## Canonical helpers (rule 6)

- C++: prefer `<algorithm>`, `std::string_view`, `std::span`, and existing project utilities over hand-written loops and buffers.
- C: reuse the project's existing string, buffer, and container helpers instead of adding near-duplicates.

## Concurrency and atomicity (rule 7)

- Manual `lock()` / `unlock()` → RAII (`std::lock_guard`, `std::scoped_lock`).
- Detached threads, or shared state without synchronization.
- Multi-step updates that leave an object half-modified when an error or exception occurs → build the new state first, then commit it (copy-and-swap).

## File size and decomposition (rule 1)

- Headers accumulating implementation, which also raises compile cost for every includer → move it to source files.
- Generated files exempt from rule 1: protobuf, parser-generator, and embedded-resource output.
