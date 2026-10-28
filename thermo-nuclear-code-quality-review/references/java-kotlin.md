# Java / Kotlin

Language-specific signals for the rules in [SKILL.md](../SKILL.md). Rule numbers refer to its Rules section.

## Idiomatic, not a smell

- An interface-plus-`Impl` pair is idiomatic when the interface is the dependency-injection, test, or published-API seam.
- Static factory methods on the type itself, and abstract skeletal implementations behind an interface (`AbstractList` style).
- Standard framework annotations (`@Transactional`, JPA, dependency injection).

## Type and boundary escapes (rule 5)

- Raw generic types, `Object` parameters where a generic fits, and `@SuppressWarnings("unchecked")` that is broad or has no comment proving the cast safe.
- `Map<String, Object>` used as a data carrier → a `record` (Java 16+) or `data class` (Kotlin).
- Java: `Optional` as a field or parameter type, or an `Optional` variable assigned `null`; unannotated nullable returns where `Optional`, an empty collection, or a `@Nullable` annotation would state the contract.
- Kotlin: `!!`, unsafe `as` casts (`as?` is the safe form), and `lateinit` covering a value that could be passed to the constructor.
- Kotlin: Java platform types leaking into Kotlin APIs without an explicit nullability decision.
- Empty or log-only `catch` blocks that silently fall back.

## Branching and spaghetti (rule 2)

- `instanceof` chains → sealed interfaces (Java 17+) with pattern-matching `switch` (Java 21+), or `when` over a sealed hierarchy (Kotlin).
- The same `switch` on an enum repeated across the codebase → constant-specific methods or an `EnumMap`, when you own the enum and the behaviour belongs to it.
- Boolean parameters that select behaviour → separate methods or an enum.

## Wrappers and magic (rule 4)

- Interface-plus-`Impl` pairs with one implementation and no seam.
- Separate `Factory`, `Manager`, or `Helper` classes that only forward to one constructor or call.
- Abstract base classes used only to share code between unrelated subclasses → composition.
- Custom reflection, AOP aspects, or annotation processors that hide control flow a direct call would show.
- Kotlin: public extension functions on broad types (`Any`, `String`) that encode domain rules → a member, a domain type, or a `private` / `internal` extension.

## Canonical helpers (rule 6)

- Prefer the JDK / Kotlin standard library and libraries already on the classpath (Guava, Apache Commons) over new near-duplicates.

## Concurrency and atomicity (rule 7)

- Independent async calls each started and joined before the next starts → start them all, then `CompletableFuture.allOf(...).join()`.
- Kotlin: independent sequential `suspend` calls → `async` / `awaitAll` inside `coroutineScope`; `GlobalScope` launches without an application-lifetime justification; `runBlocking` inside coroutine code.
- Related repository writes outside one `@Transactional` boundary. A `@Transactional` method called from its own class, or one the proxy cannot intercept (`private`; non-`public` before Spring 6), runs without a transaction.
- `synchronized` spreading across a class → a concurrent collection or a single owner of the state.

## File size and decomposition (rule 1)

- God classes accumulating unrelated responsibilities → split by responsibility.
- Kotlin files collecting many unrelated top-level declarations.
- Generated files exempt from rule 1: classes annotated `@Generated`, files with protoc's `DO NOT EDIT` header, and output under `build/generated*` (including kapt / KSP).
