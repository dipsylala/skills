# TypeScript / JavaScript

Language-specific signals for the rules in [SKILL.md](../SKILL.md). Rule numbers refer to its Rules section.

## Type and boundary escapes (rule 5)

- `any`, `as` casts, double casts (`as unknown as T`), and non-null assertions (`!`) that paper over a shape the code could describe.
- `@ts-ignore`, or `@ts-expect-error` with no explanation.
- `unknown` is correct at a true boundary (`JSON.parse`, `catch`, external input) when it is narrowed immediately by a schema or type guard. Flag it when it travels inward unnarrowed.
- Several optional properties that encode mutually exclusive modes → a discriminated union.
- `Record<string, any>` or loose object bags passed between layers → a named type, or the project's existing schema type.
- Plain JavaScript: ad-hoc object reshaping across call sites → one documented shape (JSDoc typedef or a factory) validated at the boundary.

## Branching and spaghetti (rule 2)

- `if (x.kind === ...)` chains repeated across files → a discriminated union with one exhaustive `switch` (`never` check in the default), or a lookup table.
- Boolean props accumulating on a component (`isCompact`, `isInline`, `hideHeader`) → a single `variant` prop or separate components.
- Feature-flag checks inside shared utilities → resolve the flag at the edge and pass in the chosen behaviour.

## Wrappers and magic (rule 4)

- Custom hooks that only wrap `useState` or another hook with no added meaning.
- Re-export barrels or identity wrappers that exist only to rename.
- `Proxy`, decorators, or string-keyed dynamic property access hiding a fixed set of fields.

## Canonical helpers (rule 6)

- Search the repo's utilities and installed libraries before accepting a new helper; a second debounce, deep-clone, or date formatter is a duplicate.
- Prefer platform APIs the runtime already ships (`structuredClone`, `URL`, `AbortController`, `Array.prototype.flatMap`) over bespoke equivalents.

## Concurrency and atomicity (rule 7)

- `await` inside a loop over independent items, or consecutive independent `await`s → `Promise.all` / `Promise.allSettled`, respecting rate limits.
- Floating promises (no `await`, no `void`, no `.catch`).
- React: several `setState` calls that can render an inconsistent intermediate state → one reducer or one state object.
- React: `useEffect` chains that sync derived state → compute it during render.

## File size and decomposition (rule 1)

- Components that fetch data, hold state, and render → split into a hook plus presentational subcomponents.
- Generated files exempt from rule 1: codegen output and generated `.d.ts` files.
