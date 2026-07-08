"""Small, dependency-free hierarchical state machine (HSM / UML statechart) core."""

from __future__ import annotations

from typing import ClassVar, NamedTuple


class Event:
    """Base class for triggers. Instantiate directly, or subclass to carry
    payload as fields (e.g. `class Tick(Event): surplus_w: float`).
    Dispatch matches on isinstance, so subclassing is how you model distinct
    event types."""


class Initialize(Event):
    """The event passed to on_entered for every state entered while a
    StateMachine first descends from its root down to the starting leaf."""


def event(cls: type | None = None, *, parent: type[Event] | None = None):
    """Class decorator: declare an Event without subclassing it explicitly:

        @event
        class Go:
            pass

        @event
        class Tick:
            def __init__(self, elapsed: float):
                self.elapsed = elapsed

    `parent` defaults to `Event` itself; pass a more specific `Event`
    subclass to build an event hierarchy -- since dispatch matches via
    isinstance, a Transition keyed on the parent event type also catches
    its subclasses.

    The decorated class doesn't need to subclass Event itself -- the
    decorator makes it one if it doesn't already.
    """
    base = parent if parent is not None else Event

    def decorator(target_cls: type) -> type[Event]:
        if issubclass(target_cls, Event):
            return target_cls
        namespace = {
            k: v for k, v in vars(target_cls).items() if k not in ("__dict__", "__weakref__")
        }
        return type(target_cls.__name__, (base,), namespace)

    if cls is not None:
        return decorator(cls)
    return decorator


class Transition(NamedTuple):
    event: type[Event]
    target: type["State"]
    guard: str | None = None  # human-readable only, see statemachines.md "On guards"


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
              anything conditional.

    A state's transitions very often target a sibling class defined later
    in the same file (Python can't reference a name that doesn't exist
    yet). The usual pattern is: declare every State subclass bare, then
    wire up `parent =` / `initial =` and call `add_transition` once every
    class exists -- see example.py.
    """

    parent: ClassVar[type["State"] | None] = None
    initial: ClassVar[type["State"] | None] = None
    transitions: ClassVar[tuple[Transition, ...]] = ()

    _registry: ClassVar[list[type["State"]]] = []

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        State._registry.append(cls)

    @classmethod
    def add_transition(
        cls, event: type[Event], target: type["State"], guard: str | None = None
    ) -> None:
        """Append a Transition to this state's `transitions` table."""
        cls.transitions = cls.transitions + (Transition(event, target, guard),)

    def on_entered(self, machine: "StateMachine", event: Event) -> None:
        pass

    def on_exited(self, machine: "StateMachine", event: Event) -> None:
        pass

    def on_event(self, machine: "StateMachine", event: Event) -> type["State"] | None:
        """Return the target State to transition to, or None if this state
        doesn't handle the event -- the machine bubbles the event up to
        `parent` automatically (standard statechart event bubbling)."""
        for t in type(self).transitions:
            if isinstance(event, t.event):
                return t.target
        return None


def state(cls: type | None = None, *, parent: type[State] | None = None, initial: bool = False):
    """Class decorator: declare a state's `parent` (and, from the child's
    side, whether it's that parent's `initial` state) inline, instead of
    subclassing State and assigning `.parent`/`.initial` afterward:

        @state
        class EVCharger:
            pass

        @state(parent=EVCharger, initial=True)
        class NotConnected:
            pass

    `parent` must already be a defined class, so states must be declared in
    top-down hierarchical order -- a state's `@state(parent=...)` always
    comes after its parent's own class statement. Marking the child
    `initial=True` (rather than the parent naming its initial child) is
    what makes that order-only-downward requirement possible: the parent
    never has to reference a child defined later.

    The decorated class doesn't need to subclass State itself -- the
    decorator makes it one if it doesn't already.
    """

    def decorator(target_cls: type) -> type[State]:
        if issubclass(target_cls, State):
            new_cls = target_cls
        else:
            namespace = {
                k: v for k, v in vars(target_cls).items() if k not in ("__dict__", "__weakref__")
            }
            new_cls = type(target_cls.__name__, (State,), namespace)
        new_cls.parent = parent
        if initial:
            if parent is None:
                raise ValueError(f"{new_cls.__name__} was declared initial=True but has no parent")
            if parent.initial not in (None, new_cls):
                raise ValueError(
                    f"{parent.__name__} already has an initial state "
                    f"({parent.initial.__name__}); only one child may be initial"
                )
            parent.initial = new_cls
        return new_cls

    if cls is not None:
        return decorator(cls)
    return decorator


def _ancestor_chain(state_cls: type[State]) -> list[type[State]]:
    """[state_cls, state_cls.parent, ..., None]"""
    chain = []
    cur: type[State] | None = state_cls
    while cur is not None:
        chain.append(cur)
        cur = cur.parent
    chain.append(None)
    return chain


def _leaf_of(state_cls: type[State]) -> type[State]:
    """Descend through `initial` chains until reaching an actual leaf."""
    cur = state_cls
    while cur.initial is not None:
        cur = cur.initial
    return cur


class StateMachine:
    """Holds one singleton instance per State class actually visited, so
    instance attributes (e.g. a timer set in on_entered) persist correctly
    across repeated enter/exit/re-enter cycles of the same state.
    """

    def __init__(self, root: type[State]):
        self._instances: dict[type[State], State] = {}
        leaf = _leaf_of(root)
        entry_path = list(reversed(_ancestor_chain(leaf)[:-1]))  # root..leaf
        init_event = Initialize()
        for state_cls in entry_path:
            instance = self._get_or_create(state_cls)
            instance.on_entered(self, init_event)
        self.current: State = self._get_or_create(leaf)

    def _get_or_create(self, state_cls: type[State]) -> State:
        instance = self._instances.get(state_cls)
        if instance is None:
            instance = state_cls()
            self._instances[state_cls] = instance
        return instance

    def dispatch(self, event: Event) -> None:
        """Walk the current leaf state's ancestor chain calling on_event
        until one returns a target, then transition:
          1. exit path = current leaf up to (not including) the lowest
             common ancestor of current and target; call on_exited
             leaf-to-root.
          2. entry path = LCA down to target, then descend through
             `initial` chains until reaching a leaf; call on_entered
             root-to-leaf.
        """
        current_cls = type(self.current)
        target: type[State] | None = None
        for state_cls in _ancestor_chain(current_cls)[:-1]:
            instance = self._get_or_create(state_cls)
            target = instance.on_event(self, event)
            if target is not None:
                break
        if target is None:
            return

        current_chain = _ancestor_chain(current_cls)
        target_chain = _ancestor_chain(target)
        target_chain_set = set(target_chain)
        lca: type[State] | None = None
        for state_cls in current_chain:
            if state_cls in target_chain_set:
                lca = state_cls
                break

        exit_path = current_chain[: current_chain.index(lca)]
        for state_cls in exit_path:
            self._get_or_create(state_cls).on_exited(self, event)

        entry_path_up = target_chain[: target_chain.index(lca)]
        entry_path = list(reversed(entry_path_up))
        leaf = _leaf_of(target)
        if leaf is not target:
            leaf_chain = _ancestor_chain(leaf)
            entry_path += list(reversed(leaf_chain[: leaf_chain.index(target)]))

        for state_cls in entry_path:
            self._get_or_create(state_cls).on_entered(self, event)

        self.current = self._get_or_create(leaf)
