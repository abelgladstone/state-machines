# statemachines — design doc for a standalone hierarchical state machine project

Status: **design only, not implemented.** This document exists to seed a
future standalone project (its own git repo, own `pyproject.toml`, managed
with `uv`). Nothing here has been built yet.

## Motivation

An EV charger integration in a home energy management system grew a pile
of ad-hoc timestamp/backoff fields (a "last resume attempt" timestamp, a
"resume backoff until" timestamp, a "solar dip since" timestamp, ...) to
handle real-world flakiness in the charger's reported state (a sticky
"finished" state that lingers, transient blips while it settles, noisy
solar-surplus readings on partly-cloudy days). Each new edge case added
another field and another `if` branch to the function managing charge
state. A hierarchical state machine (HSM / UML statechart) would make
each of these an explicit state with its own entry/exit/event handling,
instead of scattered boolean/timestamp bookkeeping — but building one from
scratch inside that one integration isn't worth it for a single call site.
Building it as a small, standalone, dependency-free library first — proven
out on its own — makes it reusable later, including for other threshold
logic elsewhere in the same system that has a similar "noisy signal near a
threshold causes flapping" shape.

## Goals

- A small, dependency-free, event triggered, domain-independent hierarchical state machine
  library. No knowledge of EVs, home automation platforms, or any specific
  integration belongs in this project.
- States can be nested inside other states (composite states), matching
  standard UML statechart semantics.
- A utility that takes a state machine's root state class and renders it as
  a PlantUML state diagram — useful both as living documentation and as a
  sanity check that the hierarchy you built is the one you intended.

## Core API (`statemachine/core.py`)

```python
class Event:
    """Base class for triggers. Instantiate directly, or subclass to carry
    payload as fields (e.g. `class Tick(Event): surplus_w: float`).
    Dispatch matches on isinstance, so subclassing is how you model distinct
    event types."""

class Transition(NamedTuple):
    event: type[Event]
    target: type["State"]
    guard: str | None = None  # human-readable only, see "On guards" below

class State:
    """Base class for a state.

    parent:   the State this one is nested inside, or None for a top-level
              state. Declares hierarchy; does not by itself cause any
              transition behavior.
    initial:  for a composite (non-leaf) state, which child State is entered
              by default when this state is entered without a more specific
              target already implied.
    transitions: declarative table used as this state's default on_event
              dispatch (matches the incoming event's type against the table,
              returns the first matching target). Override on_event for
              anything conditional -- see "On guards" below.
    """
    parent: ClassVar[type["State"] | None] = None
    initial: ClassVar[type["State"] | None] = None
    transitions: ClassVar[tuple[Transition, ...]] = ()

    def on_entered(self, machine: "StateMachine", event: Event | None) -> None: ...
    def on_exited(self, machine: "StateMachine", event: Event | None) -> None: ...
    def on_event(self, machine: "StateMachine", event: Event) -> type["State"] | None:
        """Return the target State to transition to, or None if this state
        doesn't handle the event -- the machine bubbles the event up to
        `parent` automatically (standard statechart event bubbling)."""
        for t in type(self).transitions:
            if isinstance(event, t.event):
                return t.target
        return None

class StateMachine:
    """Holds one singleton instance per State class actually visited, so
    instance attributes (e.g. a timer set in on_entered) persist correctly
    across repeated enter/exit/re-enter cycles of the same state.

    dispatch(event, *args, **kwargs): walk the current leaf state's
    ancestor chain calling on_event until one returns a target, then
    transition:
      1. exit path = current leaf up to (not including) the lowest common
         ancestor of current and target; call on_exited leaf-to-root.
      2. entry path = LCA down to target, then descend through `initial`
         chains until reaching a leaf; call on_entered root-to-leaf.
    This is the standard HSM transition algorithm -- nothing novel, just a
    clean small implementation of it. `event` may be an Event instance, or
    an Event subclass -- in which case it's instantiated as
    `event(*args, **kwargs)`, so `dispatch(Tick, elapsed=5)` works as
    shorthand for `dispatch(Tick(elapsed=5))`.
    """
```

## On guards

`on_event` is arbitrary imperative Python by design — it needs to check
timers, external context, whatever a real guard condition requires (that's
the whole reason to move debounce/settle/backoff logic into states instead
of ad-hoc fields). That means guard conditions generally *can't* be
recovered by static introspection.

Convention: every state should still populate its `transitions` table (with
a short `guard` string describing the condition in words, e.g. `"surplus
below threshold for longer than the debounce window"`) even when it
overrides `on_event` with real conditional logic. The table is the diagram's
source of truth and the author is responsible for keeping it honest — the
exporter does not try to parse code to infer conditions.

## PlantUML exporter (`statemachine/plantuml.py`)

```python
def generate_plantuml(root: type[State]) -> str:
    """Input is a single State class: the top of the hierarchy to render."""
```

`State.__init_subclass__` registers every defined subclass in a
module-level registry, so the exporter can find every state whose ancestor
chain includes `root` without a separately maintained list. It emits:

- nested `state Name { ... }` blocks for composite states, recursing into
  children (`child.parent is this_state`)
- `[*] --> <initial-leaf>` inside every composite, following the `initial`
  chain down to an actual leaf
- one `A --> B : Event [guard]` line per `Transition` in each state's
  `transitions` table

Pure string generation, no rendering dependency — output is `.puml` text;
paste into plantuml.com or a local PlantUML jar/plugin to render.

## Non-goals for v1

- Parallel/orthogonal regions.
- History states.
- Timer primitives baked into the library. A state that needs a timeout
  reads whatever clock/context the event carries and compares it against a
  timestamp it stored itself in `on_entered` — see the `DipHold` sketch
  below for exactly this pattern.

## Illustrative sketch: what an EV charger integration could look like ported to this

Not built now — for concreteness only, to show the kind of hierarchy this
is meant to express. This mirrors the kind of debounce fix described in
the Motivation section above (a plain "solar dip since" timestamp field),
reframed as explicit states:

```
NotConnected
Connected (composite)
├── Off
├── ForceCharge
├── ChargingFromGrid
├── ChargingFromGridNegativePrice
├── NotCharging
└── ChargingFromSolar (composite, initial=Charging)
    ├── Charging   -- surplus sufficient
    └── DipHold    -- surplus insufficient; switch stays on. on_entered
                      records self.entered_at. on_event returns to
                      NotCharging once elapsed time from self.entered_at
                      exceeds the debounce constant carried on the Tick
                      event, or back to Charging if surplus recovers first.
```

`DipHold` existing as a real state — rather than an implicit "we're
mid-debounce" condition buried in an `if` chain — is the concrete payoff
this project is meant to deliver: the state, its entry action, and its two
possible exits are all in one place instead of split across a boolean
field, a timestamp field, and scattered branches in the function that used
to manage this by hand.

## Follow-up (not part of this doc)

1. Bootstrap this project as its own repo: `pyproject.toml`,
   `statemachine/core.py`, `statemachine/plantuml.py`, tests.
2. Once proven out on its own (with its own test suite exercising the HSM
   transition algorithm, event bubbling, and the exporter), consider a
   follow-up to port the ad-hoc EV charger integration described above onto
   it, and separately evaluate whether other threshold-flapping logic
   elsewhere in the same system would benefit from the same treatment.
