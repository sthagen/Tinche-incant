import linecache
from collections import Counter
from inspect import Signature, iscoroutinefunction
from typing import Any, Callable, Final, Literal, Optional, Union

from attrs import define

from ._compat import signature


@define
class ParameterDep:
    arg_name: str
    type: Any
    default: Any = Signature.empty


CtxManagerKind = Literal["sync", "async"]


@define
class Invocation:
    """Produce an invocation (and possibly a local var) in a generated function."""

    factory: Callable
    args: list[Union[Callable, ParameterDep]]
    is_forced: bool = False
    is_ctx_manager: Optional[CtxManagerKind] = None


def compile_compose(
    fn: Callable,
    fn_args: list[Callable],
    fn_factory_args: list[str],
    outer_args: list[ParameterDep],
    invocations: list[Invocation],
    is_async: bool = False,
) -> Callable:
    """Generate the composition wrapper for `fn`.

    :param fn_factory_args: Used names to avoid for local variables.
    :param outer_args: Arguments that the generated function needs to retain.

    """
    # Some arguments need to be taken from outside.
    # Some arguments need to be calculated from factories.
    sig = signature(fn)
    fn_name = f"invoke_{fn.__name__}" if fn.__name__ != "<lambda>" else "invoke_lambda"
    globs: dict[str, Any] = {}
    arg_lines = []

    for dep in outer_args:
        if dep.type is not Signature.empty:
            # Some types, like new unions (`int|str`), do not have names.
            if (type_name := getattr(dep.type, "__name__", None)) and (
                type_name not in globs or globs[type_name] is dep.type
            ):
                arg_type_snippet = f": {type_name}"
                globs[type_name] = dep.type
            else:
                arg_type_snippet = f": _incant_arg_{dep.arg_name}"
                globs[f"_incant_arg_{dep.arg_name}"] = dep.type
        else:
            arg_type_snippet = ""
        if dep.default is not Signature.empty:
            arg_default = f"_incant_default_{dep.arg_name}"
            arg_type_snippet = f"{arg_type_snippet} = {arg_default}"
            globs[arg_default] = dep.default

        arg_lines.append(f"{dep.arg_name}{arg_type_snippet}")
    outer_arg_names = {o.arg_name for o in outer_args}

    lines = []

    ret_type = ""
    if sig.return_annotation is not Signature.empty:
        tn = getattr(sig.return_annotation, "__name__", None)
        if tn is None:
            tn = "None"
        elif tn in globs and globs[tn] is not sig.return_annotation:
            tn = "_incant_return_type"
        globs[tn] = sig.return_annotation
        ret_type = f" -> {tn}"
    if is_async:
        lines.append(f"async def {fn_name}({', '.join(arg_lines)}){ret_type}:")
    else:
        lines.append(f"def {fn_name}({', '.join(arg_lines)}){ret_type}:")

    local_vars_ix_by_factory = {
        local_var.factory: ix for ix, local_var in enumerate(invocations)
    }
    inline_exprs_by_factory: dict[Callable, str] = {}
    consts_by_factory: dict[Callable, str] = {}
    ind = 0  # Indentation level

    local_counter = 0

    # The results of some invocations are used only once.
    # In that case, we can forgo the use of a local variable.
    # We call these invocations `inlineable`.
    # An invocation is inlineable if:
    # * it is not a context manager
    # * it appears only once in the args attribute of the invocation chain.
    factory_fns = Counter(fn_args)
    for invoc in invocations:
        if invoc.is_ctx_manager:
            continue
        factory_fns.update(
            Counter(a for a in invoc.args if not isinstance(a, ParameterDep))
        )
    inlineable = {fn for fn, cnt in factory_fns.items() if cnt == 1}

    for i, invoc in enumerate(invocations):
        if _is_constant_factory(invoc):
            const_val = invoc.factory()
            global_name = _pick_name(
                (
                    invoc.factory.__name__
                    if invoc.factory.__name__ != "lambda"
                    else "lambda"
                ),
                globs,
                outer_arg_names,
                f"_incant_constant_{i}",
            )
            globs[global_name] = const_val
            consts_by_factory[invoc.factory] = global_name
            continue

        # Not a factory of constants.
        inv_fn_name = invoc.factory.__name__
        global_fn_name = _pick_name(
            inv_fn_name, globs, outer_arg_names, f"_incant_local_factory_{i}"
        )
        globs[global_fn_name] = invoc.factory

        local_arg_lines = []
        for local_arg in invoc.args:
            if isinstance(local_arg, ParameterDep):
                local_arg_lines.append(local_arg.arg_name)
            else:
                if local_arg in consts_by_factory:
                    local_arg_lines.append(consts_by_factory[local_arg])
                elif local_arg in inline_exprs_by_factory:
                    local_arg_lines.append(inline_exprs_by_factory[local_arg])
                else:
                    local_arg_lines.append(
                        f"_incant_local_{local_vars_ix_by_factory[local_arg]}"
                    )

        if invoc.factory in inlineable and not invoc.is_ctx_manager:
            aw = "await " if iscoroutinefunction(invoc.factory) else ""
            inline_exprs_by_factory[invoc.factory] = (
                f"{aw}{global_fn_name}({', '.join(local_arg_lines)})"
            )

        else:
            local_name = f"_incant_local_{local_vars_ix_by_factory[invoc.factory]}"

            if invoc.is_ctx_manager is not None:
                aw = "async " if invoc.is_ctx_manager == "async" else ""
                if not invoc.is_forced:
                    lines.append(
                        f"  {' ' * ind}{aw}with {global_fn_name}({', '.join(local_arg_lines)}) as {local_name}:"
                    )
                    local_counter += 1
                else:
                    lines.append(
                        f"  {' ' * ind}{aw}with {global_fn_name}({', '.join(local_arg_lines)}):"
                    )
                ind += 2
            else:
                aw = "await " if iscoroutinefunction(invoc.factory) else ""
                if not invoc.is_forced:
                    lines.append(
                        f"  {' ' * ind}{local_name} = {aw}{global_fn_name}({', '.join(local_arg_lines)})"
                    )
                    local_counter += 1
                else:
                    lines.append(
                        f"  {' ' * ind}{aw}{global_fn_name}({', '.join(local_arg_lines)})"
                    )

    incant_arg_lines = []
    cnt = 0
    for name in sig.parameters:
        if name not in fn_factory_args and name in outer_arg_names:
            incant_arg_lines.append(name)
        else:
            # We need to fish out the local name for this fn arg.
            factory = fn_args[cnt]

            if factory in consts_by_factory:
                incant_arg_lines.append(consts_by_factory[factory])

            elif factory in inline_exprs_by_factory:
                incant_arg_lines.append(inline_exprs_by_factory[factory])

            else:
                local_var_ix = local_vars_ix_by_factory[factory]
                incant_arg_lines.append(f"_incant_local_{local_var_ix}")
            cnt += 1

    aw = "await " if iscoroutinefunction(fn) else ""
    orig_name = fn.__name__
    inner_name = _pick_name(orig_name, globs, outer_arg_names, "_incant_inner_fn")
    globs[inner_name] = fn
    lines.append(f"  {' ' * ind}return {aw}{inner_name}({', '.join(incant_arg_lines)})")

    script = "\n".join(lines)

    fname = _generate_unique_filename(fn.__name__, "invoke", lines)
    eval(compile(script, fname, "exec"), globs)

    return globs[fn_name]


def compile_incant_wrapper(
    fn: Callable, incant_plan: list[Union[int, str]], num_pos_args: int, num_kwargs: int
):
    fn_name = f"incant_{fn.__name__}" if fn.__name__ != "<lambda>" else "incant_lambda"
    globs = {"_incant_inner_fn": fn}
    arg_lines = []
    if num_pos_args:
        arg_lines.append("*args")

    kwargs = [arg for arg in incant_plan if isinstance(arg, str)]
    arg_lines.extend(kwargs)
    if num_kwargs > len(kwargs):
        arg_lines.append("**kwargs")

    lines = []
    lines.append(f"def {fn_name}({', '.join(arg_lines)}):")
    lines.append("  return _incant_inner_fn(")
    for arg in incant_plan:
        if isinstance(arg, int):
            lines.append(f"    args[{arg}],")
        else:
            lines.append(f"    {arg},")
    lines.append("  )")

    script = "\n".join(lines)

    fname = _generate_unique_filename(fn.__name__, "incant", lines)
    eval(compile(script, fname, "exec"), globs)

    return globs[fn_name]


def _generate_unique_filename(func_name: str, func_type: str, source: list[str]) -> str:
    """
    Create a "filename" suitable for a function being generated.
    """
    extra = ""
    count = 1

    while True:
        unique_filename = f"<incant generated {func_type} of {func_name}{extra}>"
        # To handle concurrency we essentially "reserve" our spot in
        # the linecache with a dummy line.  The caller can then
        # set this value correctly.
        cache_line = (len(source), None, source, unique_filename)
        if linecache.cache.setdefault(unique_filename, cache_line) == cache_line:
            return unique_filename

        # Looks like this spot is taken. Try again.
        count += 1
        extra = f"-{count}"


def _const_fn():
    return 1  # pragma: no cover


_val = 2


def _const_fn_2():
    return _val  # pragma: no cover


_const_bytecodes: Final = {_const_fn.__code__.co_code, _const_fn_2.__code__.co_code}


def _make_const_fns():
    _inner_val = 3

    def _const_fn_3():
        return _inner_val  # pragma: no cover

    _const_bytecodes.add(_const_fn_3.__code__.co_code)


_make_const_fns()


def _is_constant_factory(invocation: Invocation) -> bool:
    """
    Is the given callable a factory of constants, and can be replaced with its result?
    """
    if iscoroutinefunction(invocation.factory):
        # We cannot run coroutines to get their constants.
        return False
    if invocation.args:
        # If there are args, it's not constant for sure.
        return False
    if invocation.is_ctx_manager:
        # Context managers are too tricky.
        return False
    if not hasattr(invocation.factory, "__code__"):
        # C functions might not have this.
        return False
    return invocation.factory.__code__.co_code in _const_bytecodes


def _pick_name(ideal: str, globs: dict[str, str], args: set[str], fallback: str) -> str:
    """Pick the best name possible for a local variable.

    If `ideal` is not available, return the fallback.
    """
    if ideal not in globs and ideal not in args and "<" not in ideal:
        return ideal

    return fallback
