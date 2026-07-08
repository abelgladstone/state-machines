"""Command-line entry point: render a State hierarchy defined in a Python
file to a PlantUML .puml file.

Usage:

    uv run statemachine-plantuml INPUT.py OUTPUT.puml [--root CLASS_NAME]
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from .core import State
from .plantuml import generate_plantuml


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _find_root(module, root_name: str | None) -> type[State]:
    candidates = [
        obj
        for obj in vars(module).values()
        if isinstance(obj, type)
        and issubclass(obj, State)
        and obj is not State
        and obj.__module__ == module.__name__
        and obj.parent is None
    ]
    if root_name is not None:
        for c in candidates:
            if c.__name__ == root_name:
                return c
        raise SystemExit(
            f"no top-level State class named {root_name!r} found in {module.__file__}"
        )
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise SystemExit(
            f"no top-level (parent=None) State class found in {module.__file__}"
        )
    names = ", ".join(c.__name__ for c in candidates)
    raise SystemExit(
        f"multiple top-level State classes found ({names}); pass --root to pick one"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Render a statemachine.State hierarchy to a PlantUML .puml file."
    )
    parser.add_argument("input", type=Path, help="Python file defining the state machine")
    parser.add_argument("output", type=Path, help="path to write the .puml file to")
    parser.add_argument(
        "--root",
        help=(
            "name of the root State class to render, if the input file "
            "defines more than one top-level (parent=None) state"
        ),
    )
    args = parser.parse_args(argv)

    module = _load_module(args.input)
    root = _find_root(module, args.root)
    args.output.write_text(generate_plantuml(root) + "\n")
    print(f"wrote {args.output} (root: {root.__name__})")


if __name__ == "__main__":
    main()
