# TypeScript / JavaScript

Language-specific signals for the rules in [SKILL.md](../SKILL.md). Rule numbers refer to its Rules section.

## Type and boundary escapes (rule 5)

- `any`, `as` casts, double casts (`as unknown as T`), and non-null assertions (`!`) that paper over a shape the code could describe.
- `@ts-ignore`, `@ts-nocheck`, or `@ts-expect-error` with no explanation.
- Values from true boundaries (`JSON.parse`, `res.json()`, `catch`, external input) belong in `unknown`, narrowed immediately by a schema or type guard. `JSON.parse` and `res.json()` return `any`, so annotate them; `catch` variables are `unknown` only under `strict` / `useUnknownInCatchVariables`. Flag the `any` used directly, or `unknown` travelling inward unnarrowed.
- `as` or a widening annotation on config objects and lookup tables → `satisfies`, which checks the value and keeps its precise type.
- Several optional properties that encode mutually exclusive modes → a discriminated union.
- `Record<string, any>` or loose object bags passed between layers → a named type, or the project's existing schema type. `Record<string, unknown>` is fine for a genuinely open map.
- Plain JavaScript: ad-hoc object reshaping across call sites → one `@typedef` shape, enforced with `// @ts-check` or `checkJs`, validated at the boundary.

## Branching and spaghetti (rule 2)

- `if (x.kind === ...)` chains repeated across files → one exhaustive `switch` (`never` default, or typescript-eslint `switch-exhaustiveness-check`), or a lookup table typed `satisfies Record<Kind, Handler>` so a missing kind fails to compile.
- Boolean props accumulating on a component (`isCompact`, `isInline`, `hideHeader`) → a single `variant` prop or separate components.
- Feature-flag checks inside shared utilities → resolve the flag at the edge and pass in the chosen behaviour.

## Wrappers and magic (rule 4)

- Custom hooks that only wrap `useState` or another hook with no added meaning, and lifecycle wrappers such as `useMount` / `useEffectOnce`.
- Internal `index.ts` barrels that only re-export, and identity wrappers that only rename. A package's public entry point is exempt.
- Custom `Proxy`s, home-grown decorators outside the framework's own conventions, or string-keyed dynamic property access standing in for a fixed set of fields.

## Canonical helpers (rule 6)

- Search the repo's utilities and installed libraries before accepting a new helper; a second debounce, deep-clone, or date formatter is a duplicate.
- Prefer platform APIs the project's runtime and `lib` setting already support (`URL`, `AbortController`, `Array.prototype.flatMap`, `structuredClone`) over bespoke equivalents. `structuredClone` drops prototypes and throws on functions, so it does not replace a deep clone of class instances.

## Concurrency and atomicity (rule 7)

- `await` inside a loop over independent items, or consecutive independent `await`s → `Promise.all` / `Promise.allSettled`, unless iterations depend on each other or rate limits apply.
- Floating promises: not awaited, returned, or given a rejection handler (`.catch(fn)`, `.then(ok, err)`). `void` marks fire-and-forget but leaves rejections unhandled.
- Async callbacks passed where a `void` return is expected (`forEach`, event handlers), and promises used as conditions.
- React: state variables that always change together, or booleans that can contradict (`isSending` + `isSent`) → one state object, a `status` value, or `useReducer`. Updates split across an `await` render separately and can read stale values; use updater functions.
- React: `useEffect` chains that sync derived state → compute it during render.

## File size and decomposition (rule 1)

- Components mixing fetch effects, state logic, and a large render tree → move fetching into a named custom hook (or the framework's data API) and extract subcomponents where the JSX is large.
- Generated files exempt from rule 1: files headed `@generated` or `DO NOT EDIT`, `__generated__/` or `*.generated.ts` paths, `.d.ts` emitted by `tsc --declaration`, and build output such as `dist/`. Hand-written `.d.ts` files are in scope.
