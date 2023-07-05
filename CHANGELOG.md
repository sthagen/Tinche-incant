# Changelog

Versions follow [CalVer](https://calver.org) with a best-effort backwards-compatibility policy.

The **first number** of the version is the year.
The **second number** is incremented with each release, starting at 1 for each year.
The **third number** is when we need to start branches for older releases (only for emergencies).

## 23.1.0 (UNRELEASED)

- Fix dependencies satisfying themselves.
- Switch to [PDM](https://pdm.fming.dev/latest/).
- Fix parameter dependencies using the new union syntax.

## 22.2.2 (2022-12-31)

- Fix an optimization for explicitly sync functions.
- Fix an issue incanting unnecessary positional arguments.
- Support `__future__` annotations (PEP 563) on Python 3.10+.

## 22.2.1 (2022-12-27)

- Fix an issue when wrapping a sync function with an async one.

## 22.2.0 (2022-12-26)

- Python 3.11 support.
- Fix `unbound local error` while generating code.
  ([#4](https://github.com/Tinche/incant/issues/4))
- Avoid using local variables in generated code when possible.
- When `incant.prepare` cannot do anything for a function, return the original function for efficiency.

## 22.1.0 (2022-09-02)

- _Breaking change_: due to limitations in autodetecting context managers (both sync and async), context manager dependencies must be explicitly registered by passing `is_context_manager="sync"` (or `async`) to the registration functions.
- Injection can be customized on a per-parameter basis by annotating a parameter with `Annotated[type, incant.Override(...)]`.
- Implement support for forced dependencies.
- Sync context managers may now be dependencies.
- `incanter.a/incant()` now handles unfulfilled parameters with defaults properly.
- Switched to CalVer.

## 0.3.0 (2022-02-03)

- Properly set the return type annotation when preparing a function.
- A hook override can now force a dependency to be promoted to a parameter (instead of being satisfied) by setting `Hook.factory` to `None`.
- Parameters with defaults are now supported for `incanter.prepare` and `incanter.a/invoke`.
- `incanter.a/incant` no longer uses `invoke` under the hood, to allow greater customization. Previous behavior can be replicated by `incant(prepare(fn))`.
- Optional arguments of dependencies can now be propagated to final function arguments. Keyword-only arguments of dependencies are still filtered out.

## 0.2.0 (2022-01-13)

- Introduce `incanter.prepare`, and make `incanter.a/invoke` use it. `prepare` just generates the prepared injection wrapper for a function and returns it, without executing it.
- Remove `incanter.parameters`, since it's now equivalent to `inspect.signature(incanter.prepare(fn)).parameters`.
- Add the ability to pass hook overrides to `incanter.prepare`, and introduce the `incanter.Hook` class to make it more usable.

## 0.1.0 (2022-01-10)

- Initial release.