"""Render a state machine's hierarchy as a PlantUML state diagram."""

from __future__ import annotations

from .core import State


def _descendants(root: type[State]) -> list[type[State]]:
    """Every registered State subclass whose ancestor chain includes root
    (including root itself)."""
    result = []
    for state_cls in State._registry:
        cur: type[State] | None = state_cls
        while cur is not None:
            if cur is root:
                result.append(state_cls)
                break
            cur = cur.parent
    return result


def _children_map(states: list[type[State]]) -> dict[type[State], list[type[State]]]:
    children: dict[type[State], list[type[State]]] = {s: [] for s in states}
    for s in states:
        if s.parent in children:
            children[s.parent].append(s)
    return children


def _emit_initial_chain(lines: list[str], indent: str, composite: type[State]) -> None:
    cur = composite.initial
    if cur is None:
        return
    lines.append(f"{indent}[*] --> {cur.__name__}")
    while cur.initial is not None:
        cur = cur.initial


def _emit_state(
    lines: list[str],
    indent: str,
    state_cls: type[State],
    children: dict[type[State], list[type[State]]],
) -> None:
    kids = children.get(state_cls, [])
    if kids:
        lines.append(f"{indent}state {state_cls.__name__} {{")
        _emit_initial_chain(lines, indent + "  ", state_cls)
        for child in kids:
            _emit_state(lines, indent + "  ", child, children)
        lines.append(f"{indent}}}")
    else:
        lines.append(f"{indent}state {state_cls.__name__}")


def generate_plantuml(root: type[State]) -> str:
    """Input is a single State class: the top of the hierarchy to render."""
    states = _descendants(root)
    children = _children_map(states)

    lines: list[str] = ["@startuml"]
    _emit_state(lines, "", root, children)

    for state_cls in states:
        for t in state_cls.transitions:
            guard = f" [{t.guard}]" if t.guard else ""
            lines.append(
                f"{state_cls.__name__} --> {t.target.__name__} : {t.event.__name__}{guard}"
            )

    lines.append("@enduml")
    return "\n".join(lines)
