# Python

Language-specific signals for the rules in [SKILL.md](../SKILL.md). Rule numbers refer to its Rules section.

## Type and boundary escapes (rule 5)

- `Any`, `typing.cast`, and `# type: ignore` without an error code or reason.
- `Optional[...]` / `X | None` on values that are never `None` in practice.
- `dict[str, Any]` or tuples passed between layers → a `dataclass`, `TypedDict`, `NamedTuple`, or the model library the project already uses.
- `**kwargs` forwarded through several layers, hiding the real signature.
- `hasattr` / `getattr` duck-typing checks scattered across call sites → a `Protocol` or an explicit type.
- Untyped code: the same dict-shape assumptions repeated in several functions signal a missing named structure.

## Branching and spaghetti (rule 2)

- `isinstance` chains → polymorphism, `functools.singledispatch`, or `match` (3.10+).
- String or boolean mode parameters (`mode="fast"`, `strict=True`) that switch behaviour deep inside a function → an `Enum` or separate functions.

## Wrappers and magic (rule 4)

- Metaclasses, `__getattr__` fallbacks, monkeypatching, and `globals()` manipulation where plain attributes or functions would do.
- Decorators that change a function's signature or return type without `functools.wraps` and a typed signature.
- Import-time side effects (network, file I/O, registration) in module bodies.

## Canonical helpers (rule 6)

- Prefer the standard library (`pathlib`, `itertools`, `functools`, `collections`, `contextlib`, `dataclasses`) and the project's existing helpers over hand-rolled equivalents.
- A growing `utils.py` signals logic that belongs in the module that owns the concept.

## Concurrency and atomicity (rule 7)

- Consecutive `await`s on independent coroutines → `asyncio.gather` or `asyncio.TaskGroup`.
- Blocking calls (`requests`, `time.sleep`, synchronous DB drivers) inside `async def`.
- Related database writes outside one transaction or unit of work.
- Mutable default arguments that share state across calls.

## File size and decomposition (rule 1)

- Logic accumulating in `__init__.py` → move it into named modules and re-export.
- Generated files exempt from rule 1: `*_pb2.py` and auto-generated migrations.
