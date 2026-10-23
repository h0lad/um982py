"""Enforces the style invariants of the library source."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "um982py"
MODULES = sorted(SRC.rglob("*.py"))
LEGACY_TYPING = {"Dict", "List", "Optional", "Set", "Tuple", "Union"}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text())


def _all_names(tree: ast.Module) -> tuple[str, ...] | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            return tuple(value)
    return None


def _all_key(name: str) -> tuple[int, str]:
    if name.isupper():
        return (0, name)
    if name[:1].isupper():
        return (1, name)
    return (2, name)


def test_every_module_has_one_line_docstring() -> None:
    for path in MODULES:
        docstring = ast.get_docstring(_tree(path))
        assert docstring is not None, path
        lines = docstring.strip().splitlines()
        assert len(lines) == 1, path
        assert lines[0].endswith("."), path
        assert len(lines[0]) <= 88, path


def test_package_initializers_publish_a_sorted_unique_all() -> None:
    for path in MODULES:
        tree = _tree(path)
        names = _all_names(tree)
        if path.name != "__init__.py" and names is None:
            continue
        assert names is not None, path
        assert len(names) == len(set(names)), path
        assert names == tuple(sorted(names, key=_all_key)), path


def test_dataclasses_are_frozen_and_slotted() -> None:
    offenders = []
    for path in MODULES:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ClassDef):
                continue
            decorators = [ast.unparse(item) for item in node.decorator_list]
            if not any(item.startswith("dataclass(") for item in decorators):
                continue
            text = " ".join(decorators)
            if "frozen=True" not in text or "slots=True" not in text:
                offenders.append(f"{path}:{node.lineno}:{node.name}")
    assert not offenders, offenders


def test_future_annotations_requires_type_checking() -> None:
    for path in MODULES:
        source = path.read_text()
        tree = _tree(path)
        has_future = any(
            isinstance(node, ast.ImportFrom) and node.module == "__future__"
            for node in tree.body
        )
        if has_future:
            assert "TYPE_CHECKING" in source, path


def test_legacy_typing_spellings_are_not_used() -> None:
    offenders = []
    for path in MODULES:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom) and node.module == "typing":
                imported = {alias.name for alias in node.names}
                offenders.extend(
                    f"{path}:{node.lineno}:{name}" for name in imported & LEGACY_TYPING
                )
    assert not offenders, offenders


def test_except_handlers_name_their_exception() -> None:
    offenders = [
        f"{path}:{node.lineno}"
        for path in MODULES
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.ExceptHandler) and node.type is None
    ]
    assert not offenders, offenders


def test_public_definitions_are_fully_annotated() -> None:
    offenders = [
        f"{path}:{node.lineno}:{node.name}({argument.arg})"
        for path in MODULES
        for node in ast.walk(_tree(path))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        if argument.arg not in ("self", "cls") and argument.annotation is None
    ]
    offenders.extend(
        f"{path}:{node.lineno}:{node.name}"
        for path in MODULES
        for node in ast.walk(_tree(path))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
        and node.returns is None
    )
    assert not offenders, offenders


def test_public_names_follow_the_style_guide() -> None:
    offenders = [
        f"{path}:{node.lineno}:{node.name}"
        for path in MODULES
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.ClassDef)
        and not node.name.startswith("_")
        and not node.name[:1].isupper()
    ]
    offenders.extend(
        f"{path}:{node.lineno}:{node.name}"
        for path in MODULES
        for node in ast.walk(_tree(path))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
        and node.name != node.name.lower()
    )
    assert not offenders, offenders


def test_library_has_no_assertions_or_placeholders() -> None:
    offenders = [
        f"{path}:{node.lineno}"
        for path in MODULES
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Assert)
    ]
    offenders.extend(
        f"{path}:{number}"
        for path in MODULES
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if "TODO" in line or "FIXME" in line or "XXX" in line
    )
    assert not offenders, offenders


def test_library_uses_path_helpers_instead_of_builtin_open() -> None:
    offenders = [
        f"{path}:{node.lineno}"
        for path in MODULES
        for node in ast.walk(_tree(path))
        if (
            (isinstance(node, ast.Call) and ast.unparse(node.func) == "open")
            or (
                isinstance(node, ast.Attribute)
                and ast.unparse(node).startswith("os.path")
            )
        )
    ]
    assert not offenders, offenders
