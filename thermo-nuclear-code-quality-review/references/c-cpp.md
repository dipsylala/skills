# C / C++

Language-specific signals for the rules in [SKILL.md](../SKILL.md). Rule numbers refer to its Rules section.

## Idiomatic, not a smell

- C: a `goto` chain of cleanup labels on error paths, releasing resources in reverse order of acquisition. In C++, use RAII instead.
- Long `switch` statements over an enum the module owns, with every case handled and no `default`, so the compiler flags new enumerators.
- C: `void*` plus a callback where no typed generic mechanism exists (`qsort` style).
- Templates and small `inline` / `constexpr` functions in headers.

## Type and boundary escapes (rule 5)

- `void*` parameters and C-style casts where a typed interface fits.
- C++: `reinterpret_cast`, and `const_cast` used to drop `const` (wrap const-incorrect legacy APIs instead).
- Implicit narrowing conversions → brace initialization or a checked narrowing helper.
- C++: raw owning pointers or naked `new` / `delete` → `std::unique_ptr`; `std::shared_ptr` only for genuinely shared ownership.
- Out-parameters plus a `bool` or sentinel return → a return value: `std::optional` (C++17) or `std::expected` (C++23) in C++, a result struct in C.
- Error codes or status returns that callers can silently ignore → `[[nodiscard]]` (C++17, C23).
- Macros used as constants or functions → `constexpr`, `inline`, or template functions (C++); `enum` constants or `static inline` functions (C99+).
- `int` flags encoding modes → an `enum` (`enum class` in C++); untagged unions → a tagged union or `std::variant` (C++17).

## Branching and spaghetti (rule 2)

- `#ifdef` platform or feature checks spread through shared code → isolate them in headers or a platform layer with stub functions.
- The same switch on a type tag in several places → virtual dispatch, or `std::variant` with `std::visit`.

## Wrappers and magic (rule 4)

- Macro-built DSLs, and template metaprogramming (`enable_if`, type-level recursion) where a plain function, overload, `constexpr` function, or concept would do.
- Deep inheritance hierarchies used for code sharing → composition.

## Canonical helpers (rule 6)

- C++: prefer `<algorithm>`, `std::string_view` (C++17), and `std::span` (C++20) over hand-written loops and pointer-plus-length pairs; watch `string_view` for dangling references.
- C: reuse the project's existing string, buffer, and container helpers instead of adding near-duplicates.

## Concurrency and atomicity (rule 7)

- Manual `lock()` / `unlock()` → RAII (`std::lock_guard`, `std::scoped_lock` for several mutexes, `std::unique_lock` when a condition variable needs it).
- Detached threads, or threads joined by hand → `std::jthread` (C++20); shared writable state without synchronization.
- Multi-step updates that leave an object half-modified when an error or exception occurs → do the work that can fail on a temporary, then commit with non-throwing operations such as `swap`.

## File size and decomposition (rule 1)

- Headers accumulating non-template implementation, which raises compile cost for every includer → move it to source files.
- Generated files exempt from rule 1: protobuf, parser-generator, and embedded-resource output.
