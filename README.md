# statemachine

A small, dependency-free, event-triggered hierarchical state machine (HSM /
UML statechart) library for Python. States can nest inside other states
(composite states), events bubble up the hierarchy when a state doesn't
handle them, and a machine's hierarchy can be exported as a PlantUML
diagram. See [`statemachines.md`](statemachines.md) for the full design
rationale.

## Install

Managed with [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync
```

No third-party dependencies are pulled in — the library itself has none.

## Core concepts

- **`Event`** — base class for triggers. Instantiate directly, or subclass
  to carry payload (`class Tick(Event): ...`). Matching is by `isinstance`,
  so subclassing is how you model distinct event types. `@event` (see
  below) declares one without subclassing explicitly.
- **`State`** — base class for a state. Class attributes declare the
  hierarchy and default dispatch table:
  - `parent` — the `State` this one nests inside, or `None` for the root.
  - `initial` — for a composite state, which child is entered by default.
  - `transitions` — a tuple of `Transition(event, target, guard=None)`;
    the default `on_event` scans this table and returns the first match.
    Build it up with `SomeState.add_transition(event, target, guard=None)`
    calls rather than one big literal — see Quickstart below for why.
  - Override `on_entered`, `on_exited`, `on_event` for real behavior
    (timers, conditional/guarded transitions, etc). `on_event` should
    return the target `State` class, or `None` to let the event bubble up
    to `parent`.
- **`StateMachine(root)`** — drives one machine. Holds one singleton
  instance per `State` class actually visited (so instance attributes set
  in `on_entered`, like a debounce timer, persist across re-entry).
  `machine.current` is the current leaf state instance;
  `machine.dispatch(event)` runs the standard HSM transition algorithm
  (bubble the event up for a handler, exit up to the lowest common
  ancestor, then enter back down to the target, descending through
  `initial` chains to a leaf).
- **`generate_plantuml(root)`** — renders a machine's full hierarchy as a
  `.puml` string (nested `state { }` blocks, `[*] -->` for `initial`
  chains, `A --> B : Event [guard]` for each transition). Paste the output
  into [plantuml.com](https://www.plantuml.com/plantuml) or a local
  PlantUML renderer.

### Root-naming convention

Every machine has exactly **one** root `State` class (`parent = None`),
named after the machine itself (e.g. `EVCharger`) — not a generic
placeholder. Everything else, including what look like independent
top-level regions (e.g. `NotConnected` / `Connected`), nests under that one
root via `parent =`. There's no notion of multiple sibling root states in
a single machine; the root class *is* the boundary of the "state
universe."

## Quickstart

```python
from statemachine import StateMachine, event, generate_plantuml, state


@event
class Go:
    pass


@event
class Back:
    pass


@state
class Light:             # the root — named for the machine
    pass


@state(parent=Light, initial=True)
class Red:
    pass


@state(parent=Light)
class Green:
    pass


Red.add_transition(Go, Green)
Green.add_transition(Back, Red)

machine = StateMachine(Light)
print(type(machine.current).__name__)   # Red

machine.dispatch(Go())
print(type(machine.current).__name__)   # Green

print(generate_plantuml(Light))
```

### The `@state` decorator, and why declaration order matters

`@state(parent=..., initial=False)` declares a state's `parent` (making it
a real `State` subclass if it isn't one already) without needing to
subclass `State` and assign `.parent` afterward. Because `parent` must
already be a defined class when you pass it, **states have to be declared
top-down** — a state's `@state(parent=...)` always comes after its
parent's own class statement (`Light` before `Red`/`Green`, `Connected`
before `Idle`, etc). Marking a child `initial=True` (rather than having
the parent name its initial child) is what makes purely top-down order
possible: the parent never has to reference a child defined later. Only
one child per parent may be `initial=True` — a second one raises
`ValueError`.

A bare `@state` (no parentheses) is shorthand for `@state()` — a root with
no parent.

### The `@event` decorator

`@event(parent=None)` is the same idea for events: declares an `Event`
subclass without writing `class Go(Event): pass`. A custom `__init__` for
payload fields (like `Tick` in `example.py`) works the same as it would on
a real subclass — the decorator only changes what the class inherits from,
not what's in its body. `parent` defaults to `Event` itself; pass a more
specific `Event` subclass to build an event hierarchy, since dispatch
matches via `isinstance` — a `Transition` keyed on the parent event type
also catches its subclasses:

```python
@event
class NetworkEvent:
    pass

@event(parent=NetworkEvent)
class Connected:
    pass

# a transition on NetworkEvent also fires for Connected
SomeState.add_transition(NetworkEvent, OtherState)
```

Unlike `@state`, there's no ordering requirement here — events have no
`parent`/`initial` chain to walk, `parent` just names an already-declared
`Event` subclass.

### Transitions still need a second pass

A state's transitions very often target a *sibling* rather than an
ancestor/descendant (`Idle` needing to name `ChargingFromGrid`, defined
after it) — no declaration order makes every sibling reference
backward-only. So transitions are wired up separately, after every state
in the machine is declared, with `SomeState.add_transition(event, target,
guard=None)`:

```python
Idle.add_transition(StartGridCharge, ChargingFromGrid)
Idle.add_transition(StartSolarCharge, ChargingFromSolar)
```

`add_transition` just appends a `Transition` to the state's `transitions`
tuple, one call per transition, all with real class references — see
`example.py` for the full pattern.

## Example: interactive CLI

[`example.py`](example.py) is a runnable demo of a (fictional, simplified)
EV charger built on this library — the same shape sketched as the
motivating use case in `statemachines.md`: `NotConnected` / `Connected`,
with `Connected` containing `Idle`, `ChargingFromGrid`, and a composite
`ChargingFromSolar` with a debounced `DipHold` state that only drops back
to `Idle` once enough elapsed time has accumulated without the surplus
recovering.

Run it:

```bash
uv run python example.py
```

Then type commands to dispatch events; after each one it prints the
current state path and an ASCII tree of the whole machine with the current
leaf marked:

```
(evcharger) connect
current state: EVCharger > Connected > Idle
EVCharger
├── NotConnected
└── Connected
    ├── Idle  <-- current
    ├── ChargingFromGrid
    └── ChargingFromSolar
        ├── Charging
        └── DipHold
```

Type `help` to list all commands (`connect`, `disconnect`, `start_grid`,
`start_solar`, `stop`, `surplus_low`, `surplus_high`, `tick <seconds>`,
`state`, `plantuml`, `quit`). `plantuml` prints the machine's full PlantUML
diagram.

## Rendering PlantUML from the command line

`statemachine-plantuml` renders any Python file that defines a state
machine to a `.puml` file, without needing a Python REPL:

```bash
uv run statemachine-plantuml INPUT.py OUTPUT.puml
```

For example:

```bash
uv run statemachine-plantuml example.py evcharger.puml
```

It imports `INPUT.py`, finds the file's top-level (`parent = None`) `State`
class as the root, renders it with `generate_plantuml`, and writes the
result to `OUTPUT.puml`. If the file defines more than one top-level state
(unusual — see the root-naming convention above), pass `--root CLASS_NAME`
to disambiguate:

```bash
uv run statemachine-plantuml INPUT.py OUTPUT.puml --root EVCharger
```

Paste the resulting `.puml` file into
[plantuml.com](https://www.plantuml.com/plantuml) or a local PlantUML
renderer to view the diagram.

## Tests

```bash
uv run python -m unittest discover tests/ -v
```
