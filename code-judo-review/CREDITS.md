# Credits

The skill's rules, review stance, and example comments are adapted from the [Cursor Team thermo-nuclear code quality review](https://github.com/cursor/plugins/tree/main/cursor-team-kit/skills/thermo-nuclear-code-quality-review) skill. It was published in this repository as `thermo-nuclear-code-quality-review` before becoming a review-only skill with per-language references and taking the name `code-judo-review`.

The language references in [`references/`](references/) were checked bullet by bullet against the sources below. Where no primary source covers a point (for example, splitting god classes or repeated switches), the bullet reflects widely accepted practice, usually from Martin Fowler's [*Refactoring*](https://refactoring.com/catalog/) (2nd ed.) or his [bliki](https://martinfowler.com/bliki/) ([FlagArgument](https://martinfowler.com/bliki/FlagArgument.html), [InterfaceImplementationPair](https://martinfowler.com/bliki/InterfaceImplementationPair.html)).

## TypeScript / JavaScript

- TypeScript Handbook: [Narrowing](https://www.typescriptlang.org/docs/handbook/2/narrowing.html), [Everyday Types](https://www.typescriptlang.org/docs/handbook/2/everyday-types.html), [JSDoc Reference](https://www.typescriptlang.org/docs/handbook/jsdoc-supported-types.html), [TSConfig `useUnknownInCatchVariables`](https://www.typescriptlang.org/tsconfig/#useUnknownInCatchVariables), and release notes for [3.9](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-3-9.html), [4.9](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-4-9.html), and [5.0](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-0.html)
- typescript-eslint rules: [no-explicit-any](https://typescript-eslint.io/rules/no-explicit-any/), [no-non-null-assertion](https://typescript-eslint.io/rules/no-non-null-assertion/), [ban-ts-comment](https://typescript-eslint.io/rules/ban-ts-comment/), [consistent-type-assertions](https://typescript-eslint.io/rules/consistent-type-assertions/), [no-floating-promises](https://typescript-eslint.io/rules/no-floating-promises/), [no-misused-promises](https://typescript-eslint.io/rules/no-misused-promises/), [switch-exhaustiveness-check](https://typescript-eslint.io/rules/switch-exhaustiveness-check/), [no-unsafe-assignment](https://typescript-eslint.io/rules/no-unsafe-assignment/)
- ESLint [no-await-in-loop](https://eslint.org/docs/latest/rules/no-await-in-loop)
- React: [You Might Not Need an Effect](https://react.dev/learn/you-might-not-need-an-effect), [Choosing the State Structure](https://react.dev/learn/choosing-the-state-structure), [Queueing a Series of State Updates](https://react.dev/learn/queueing-a-series-of-state-updates), [Extracting State Logic into a Reducer](https://react.dev/learn/extracting-state-logic-into-a-reducer), [Reusing Logic with Custom Hooks](https://react.dev/learn/reusing-logic-with-custom-hooks)
- MDN: [structuredClone()](https://developer.mozilla.org/en-US/docs/Web/API/Window/structuredClone), [Structured clone algorithm](https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API/Structured_clone_algorithm), [Promise.all()](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise/all)
- [Vite performance guide](https://vite.dev/guide/performance) (barrel files)
- Pete Hodgson, [Feature Toggles](https://martinfowler.com/articles/feature-toggles.html)

## Python

- PEPs: [8](https://peps.python.org/pep-0008/), [484](https://peps.python.org/pep-0484/), [544](https://peps.python.org/pep-0544/), [586](https://peps.python.org/pep-0586/), [589](https://peps.python.org/pep-0589/), [604](https://peps.python.org/pep-0604/), [612](https://peps.python.org/pep-0612/), [636](https://peps.python.org/pep-0636/), [692](https://peps.python.org/pep-0692/)
- Python docs: [typing](https://docs.python.org/3/library/typing.html), [functools](https://docs.python.org/3/library/functools.html), [asyncio tasks](https://docs.python.org/3/library/asyncio-task.html), [asyncio development](https://docs.python.org/3/library/asyncio-dev.html), [Programming FAQ](https://docs.python.org/3/faq/programming.html#why-are-default-values-shared-between-objects), [Glossary](https://docs.python.org/3/glossary.html)
- [mypy error codes](https://mypy.readthedocs.io/en/stable/error_codes.html)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- [Protobuf Python generated code](https://protobuf.dev/reference/python/python-generated/), [Django migrations](https://docs.djangoproject.com/en/stable/topics/migrations/), [Alembic autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)

## Go

- [Effective Go](https://go.dev/doc/effective_go), [Go Code Review Comments](https://go.dev/wiki/CodeReviewComments), [Go FAQ](https://go.dev/doc/faq), [MutexOrChannel](https://go.dev/wiki/MutexOrChannel)
- Google Go Style: [Decisions](https://google.github.io/styleguide/go/decisions), [Best Practices](https://google.github.io/styleguide/go/best-practices)
- Go blog: [Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors), [On | No syntactic support for error handling](https://go.dev/blog/error-syntax)
- [Go 1.21 release notes](https://go.dev/doc/go1.21), [sync](https://pkg.go.dev/sync), [errgroup](https://pkg.go.dev/golang.org/x/sync/errgroup), [cmd/go generated-file convention](https://pkg.go.dev/cmd/go#hdr-Generate_Go_files_by_processing_source)
- [Go Proverbs](https://go-proverbs.github.io/); Dave Cheney, [Functional options for friendly APIs](https://dave.cheney.net/2014/10/17/functional-options-for-friendly-apis)

## Rust

- [The Rust Programming Language](https://doc.rust-lang.org/book/), [The Rust Reference](https://doc.rust-lang.org/reference/expressions/operator-expr.html), [standard library docs](https://doc.rust-lang.org/std/), [Cargo build scripts](https://doc.rust-lang.org/cargo/reference/build-scripts.html)
- [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/) (C-GOOD-ERR, C-CUSTOM-TYPE, C-DEREF, C-NEWTYPE, C-SEALED)
- [Clippy lint list](https://rust-lang.github.io/rust-clippy/master/index.html)
- [Rust Design Patterns](https://rust-unofficial.github.io/patterns/)
- [Tokio API docs](https://docs.rs/tokio/latest/tokio/)
- Rust release announcements: [1.65](https://blog.rust-lang.org/2022/11/03/Rust-1.65.0.html), [1.81](https://blog.rust-lang.org/2024/09/05/Rust-1.81.0/), [1.88](https://blog.rust-lang.org/2025/06/26/Rust-1.88.0/)

## Java / Kotlin

- Joshua Bloch, *Effective Java*, 3rd ed. (Addison-Wesley, 2018)
- Java SE 21 API: [Optional](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/Optional.html), [CompletableFuture](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/concurrent/CompletableFuture.html), [Generated](https://docs.oracle.com/en/java/javase/21/docs/api/java.compiler/javax/annotation/processing/Generated.html)
- JEPs: [361](https://openjdk.org/jeps/361), [394](https://openjdk.org/jeps/394), [395](https://openjdk.org/jeps/395), [409](https://openjdk.org/jeps/409), [441](https://openjdk.org/jeps/441)
- Kotlin docs: [Null safety](https://kotlinlang.org/docs/null-safety.html), [Java interop](https://kotlinlang.org/docs/java-interop.html), [Properties](https://kotlinlang.org/docs/properties.html), [Coding conventions](https://kotlinlang.org/docs/coding-conventions.html), [Sealed classes](https://kotlinlang.org/docs/sealed-classes.html), [Composing suspending functions](https://kotlinlang.org/docs/composing-suspending-functions.html)
- kotlinx.coroutines: [GlobalScope](https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines/-global-scope/), [awaitAll](https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines/await-all.html), [runBlocking](https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines/run-blocking.html)
- Spring Framework, [Using @Transactional](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/annotations.html)

## C\#

- .NET Framework Design Guidelines: [Parameter Design](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/parameter-design), [Extension Methods](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/extension-methods)
- C# docs: [null-forgiving operator](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/operators/null-forgiving), [nullable migration strategies](https://learn.microsoft.com/en-us/dotnet/csharp/advanced-topics/update-applications/nullable-migration-strategies), [pattern matching](https://learn.microsoft.com/en-us/dotnet/csharp/fundamentals/functional/pattern-matching), [switch expression](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/operators/switch-expression), [records](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/builtin-types/record), [partial classes](https://learn.microsoft.com/en-us/dotnet/csharp/programming-guide/classes-and-structs/partial-classes-and-methods)
- Code analysis: [CA1031](https://learn.microsoft.com/en-us/dotnet/fundamentals/code-analysis/quality-rules/ca1031), [CA2016](https://learn.microsoft.com/en-us/dotnet/fundamentals/code-analysis/quality-rules/ca2016), [generated code configuration](https://learn.microsoft.com/en-us/dotnet/fundamentals/code-analysis/configuration-options)
- [.NET dependency injection](https://learn.microsoft.com/en-us/dotnet/core/extensions/dependency-injection), [preparing libraries for trimming](https://learn.microsoft.com/en-us/dotnet/core/deploying/trimming/prepare-libraries-for-trimming)
- EF Core: [Transactions](https://learn.microsoft.com/en-us/ef/core/saving/transactions), [DbContext threading](https://learn.microsoft.com/en-us/ef/core/dbcontext-configuration/)
- Stephen Cleary, [Async/Await – Best Practices in Asynchronous Programming](https://learn.microsoft.com/en-us/archive/msdn-magazine/2013/march/async-await-best-practices-in-asynchronous-programming); David Fowler, [AsyncGuidance](https://github.com/davidfowl/AspNetCoreDiagnosticScenarios/blob/master/AsyncGuidance.md)
- [StyleCop SA1402](https://github.com/DotNetAnalyzers/StyleCopAnalyzers/blob/master/documentation/SA1402.md)

## C / C++

- [C++ Core Guidelines](https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines)
- [SEI CERT C Coding Standard](https://cmu-sei.github.io/secure-coding-standards/sei-cert-c-coding-standard/) (MEM12-C, PRE00-C, DCL06-C)
- [Linux kernel coding style](https://www.kernel.org/doc/html/latest/process/coding-style.html)
- [GCC warning options](https://gcc.gnu.org/onlinedocs/gcc/Warning-Options.html) (`-Wswitch`)
