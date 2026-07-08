"""Interactive CLI demo of the statemachine library.

Models a (simplified, fictional) EV charger: connect/disconnect, start
charging from the grid or from solar, and a debounced "surplus dip" hold
state -- the exact shape sketched in statemachines.md as the motivating
use case for this library.

Run it:

    uv run python example.py

Then type commands (see `help`) to dispatch events; after each one the
current state path and an ASCII tree of the whole machine (current leaf
marked) are printed.
"""

from __future__ import annotations

import cmd

from statemachine import Event, State, StateMachine, event, generate_plantuml, state

DEBOUNCE_SECONDS = 10.0


# --- events ----------------------------------------------------------------


@event
class Connect:
    pass


@event
class Disconnect:
    pass


@event
class StartGridCharge:
    pass


@event
class StartSolarCharge:
    pass


@event
class Stop:
    pass


@event
class SurplusLow:
    pass


@event
class SurplusHigh:
    pass


@event
class Tick:
    def __init__(self, elapsed: float):
        self.elapsed = elapsed


# --- states ------------------------------------------------------------
#
# Root class is named for the machine itself (EVCharger); everything else
# nests under it -- see statemachines.md's root-naming convention. States
# are declared top-down with @state(parent=..., initial=...): a state's
# decorator always comes after its parent's class statement, so `parent`
# is always a real, already-defined class -- no forward references. A
# child marks itself `initial=True` rather than the parent naming its
# initial child, which is what keeps the ordering purely top-down.
#
# Transitions still need `add_transition` calls after every class exists,
# since a transition's target is very often a *sibling* (not an ancestor),
# and there's no ordering that makes every sibling reference backward-only.


@state
class EVCharger:
    pass


@state(parent=EVCharger, initial=True)
class NotConnected:
    pass


@state(parent=EVCharger)
class Connected:
    pass


@state(parent=Connected, initial=True)
class Idle:
    pass


@state(parent=Connected)
class ChargingFromGrid:
    pass


@state(parent=Connected)
class ChargingFromSolar:
    pass


@state(parent=ChargingFromSolar, initial=True)
class Charging:
    pass


@state(parent=ChargingFromSolar)
class DipHold:
    def on_entered(self, machine, event):
        self.elapsed = 0.0

    def on_event(self, machine, event):
        if isinstance(event, SurplusHigh):
            return Charging
        if isinstance(event, Tick):
            self.elapsed += event.elapsed
            if self.elapsed >= DEBOUNCE_SECONDS:
                return Idle
        return None


NotConnected.add_transition(Connect, Connected)
Connected.add_transition(Disconnect, NotConnected)
Idle.add_transition(StartGridCharge, ChargingFromGrid)
Idle.add_transition(StartSolarCharge, ChargingFromSolar)
ChargingFromGrid.add_transition(Stop, Idle)
ChargingFromSolar.add_transition(Stop, Idle)
Charging.add_transition(SurplusLow, DipHold, guard="surplus below threshold")
DipHold.add_transition(SurplusHigh, Charging, guard="surplus recovered")
DipHold.add_transition(
    Tick, Idle, guard=f"accumulated elapsed >= {DEBOUNCE_SECONDS:g}s without recovery"
)

STATE_ORDER = (
    EVCharger,
    NotConnected,
    Connected,
    Idle,
    ChargingFromGrid,
    ChargingFromSolar,
    Charging,
    DipHold,
)


# --- ascii tree rendering ----------------------------------------------


def _children(node: type[State]) -> list[type[State]]:
    return [s for s in STATE_ORDER if s.parent is node]


def render_tree(root: type[State], current: type[State]) -> str:
    def label(node: type[State]) -> str:
        return node.__name__ + ("  <-- current" if node is current else "")

    lines = [label(root)]

    def walk(node: type[State], prefix: str, is_last: bool) -> None:
        connector = "└── " if is_last else "├── "
        lines.append(prefix + connector + label(node))
        kids = _children(node)
        next_prefix = prefix + ("    " if is_last else "│   ")
        for i, kid in enumerate(kids):
            walk(kid, next_prefix, i == len(kids) - 1)

    kids = _children(root)
    for i, kid in enumerate(kids):
        walk(kid, "", i == len(kids) - 1)
    return "\n".join(lines)


def _state_path(leaf: type[State]) -> str:
    chain = []
    cur: type[State] | None = leaf
    while cur is not None:
        chain.append(cur.__name__)
        cur = cur.parent
    return " > ".join(reversed(chain))


# --- CLI -----------------------------------------------------------------


class EVChargerShell(cmd.Cmd):
    intro = (
        "statemachine EV charger demo. Type `help` for commands, `state` to\n"
        "see the current state and diagram, `quit` to exit.\n"
    )
    prompt = "(evcharger) "

    def __init__(self):
        super().__init__()
        self.machine = StateMachine(EVCharger)
        self._show()

    def _show(self) -> None:
        leaf = type(self.machine.current)
        print(f"current state: {_state_path(leaf)}")
        print(render_tree(EVCharger, leaf))

    def _dispatch(self, event: Event) -> None:
        self.machine.dispatch(event)
        self._show()

    def do_connect(self, arg):
        "Dispatch Connect (NotConnected -> Connected)."
        self._dispatch(Connect())

    def do_disconnect(self, arg):
        "Dispatch Disconnect (any Connected substate -> NotConnected)."
        self._dispatch(Disconnect())

    def do_start_grid(self, arg):
        "Dispatch StartGridCharge (Idle -> ChargingFromGrid)."
        self._dispatch(StartGridCharge())

    def do_start_solar(self, arg):
        "Dispatch StartSolarCharge (Idle -> ChargingFromSolar/Charging)."
        self._dispatch(StartSolarCharge())

    def do_stop(self, arg):
        "Dispatch Stop (any charging substate -> Idle)."
        self._dispatch(Stop())

    def do_surplus_low(self, arg):
        "Dispatch SurplusLow (Charging -> DipHold)."
        self._dispatch(SurplusLow())

    def do_surplus_high(self, arg):
        "Dispatch SurplusHigh (DipHold -> Charging)."
        self._dispatch(SurplusHigh())

    def do_tick(self, arg):
        "Dispatch Tick <seconds> (accumulates elapsed time while in DipHold)."
        try:
            elapsed = float(arg.strip() or "1")
        except ValueError:
            print("usage: tick <seconds>")
            return
        self._dispatch(Tick(elapsed))

    def do_state(self, arg):
        "Print the current state path and ASCII diagram."
        self._show()

    def do_plantuml(self, arg):
        "Print the full machine as a PlantUML state diagram."
        print(generate_plantuml(EVCharger))

    def do_quit(self, arg):
        "Exit."
        return True

    def do_EOF(self, arg):
        "Exit on Ctrl-D."
        print()
        return True


if __name__ == "__main__":
    EVChargerShell().cmdloop()
