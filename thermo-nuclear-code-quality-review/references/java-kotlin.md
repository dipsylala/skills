# Java / Kotlin

Language-specific signals for the rules in [SKILL.md](../SKILL.md). Rule numbers refer to its Rules section.

## Type and boundary escapes (rule 5)

- Raw generic types, `Object` parameters, and unchecked casts behind `@SuppressWarnings("unchecked")`.
- `Map<String, Object>` used as a data carrier → a `record` (Java) or `data class` (Kotlin).
- Java: `Optional` as a field or parameter type; `null` returned where the contract is unclear.
- Kotlin: `!!`, unsafe `as` casts, and `lateinit` covering a value that could be passed to the constructor.
- Kotlin: Java platform types leaking into Kotlin APIs without an explicit nullability decision.

## Branching and spaghetti (rule 2)

- `instanceof` chains → sealed interfaces with pattern-matching `switch` (Java 21+) or `when` over a sealed hierarchy (Kotlin).
- The same `switch` on an enum in several places → behaviour on the enum constants.
- Boolean parameters that select behaviour → separate methods or an enum.

## Wrappers and magic (rule 4)

- Interface-plus-`Impl` pairs with one implementation and no test or module seam.
- Factories, `Manager`, or `Helper` classes that wrap a single constructor or call.
- Abstract base classes used only to share code → composition.
- Reflection, AOP, or annotation-driven behaviour that hides control flow a direct call would show.
- Kotlin: extension functions on broad types (`Any`, `String`) that encode domain rules.

## Canonical helpers (rule 6)

- Prefer the JDK / Kotlin standard library and libraries already on the classpath (Guava, Apache Commons) over new near-duplicates.

## Concurrency and atomicity (rule 7)

- `CompletableFuture`s joined one at a time → `CompletableFuture.allOf`.
- Kotlin: independent sequential `suspend` calls → `async` / `awaitAll` inside `coroutineScope`; `GlobalScope` launches.
- Related repository writes outside one `@Transactional` boundary.
- `synchronized` spreading across a class → a concurrent collection or a single owner of the state.

## File size and decomposition (rule 1)

- God classes accumulating unrelated responsibilities → split by responsibility.
- Kotlin files collecting many unrelated top-level declarations.
- Generated files exempt from rule 1: protobuf, OpenAPI, and annotation-processor output.
