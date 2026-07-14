import unittest

from statemachine.core import Event, Initialize, State, StateMachine, Transition, event, state


class Log:
    """Shared recorder so tests can assert on_entered/on_exited/dispatch order."""

    def __init__(self):
        self.events: list[str] = []


class Go(Event):
    pass


class Back(Event):
    pass


class TickWithCount(Event):
    def __init__(self, n: int):
        self.n = n


# --- flat machine -----------------------------------------------------


class FlatState(State):
    log: Log

    def on_entered(self, machine, event):
        self.log.events.append(f"enter:{type(self).__name__}")

    def on_exited(self, machine, event):
        self.log.events.append(f"exit:{type(self).__name__}")


def make_flat(log: Log):
    class A(FlatState):
        pass

    class B(FlatState):
        transitions = ()

    A.transitions = (Transition(Go, B),)
    B.transitions = (Transition(Back, A),)

    for cls in (A, B):
        cls.log = log

    return A, B


class StateDecoratorTests(unittest.TestCase):
    def test_bare_decorator_declares_a_root_with_no_parent(self):
        @state
        class Root:
            pass

        self.assertTrue(issubclass(Root, State))
        self.assertIsNone(Root.parent)

    def test_parent_kwarg_sets_parent_and_registers_as_state_subclass(self):
        @state
        class Root:
            pass

        @state(parent=Root)
        class Child:
            pass

        self.assertIs(Child.parent, Root)
        self.assertIn(Child, State._registry)

    def test_initial_true_sets_parent_initial_to_this_child(self):
        @state
        class Root:
            pass

        @state(parent=Root, initial=True)
        class FirstChild:
            pass

        self.assertIs(Root.initial, FirstChild)

    def test_initial_true_without_parent_raises(self):
        with self.assertRaises(ValueError):

            @state(initial=True)
            class Orphan:
                pass

    def test_second_initial_true_for_same_parent_raises(self):
        @state
        class Root:
            pass

        @state(parent=Root, initial=True)
        class FirstChild:
            pass

        with self.assertRaises(ValueError):

            @state(parent=Root, initial=True)
            class SecondChild:
                pass

    def test_decorated_states_work_in_a_real_machine(self):
        @state
        class Root:
            pass

        @state(parent=Root, initial=True)
        class A:
            pass

        @state(parent=Root)
        class B:
            pass

        A.add_transition(Go, B)
        B.add_transition(Back, A)

        machine = StateMachine(Root)
        self.assertIs(type(machine.current), A)

        machine.dispatch(Go())
        self.assertIs(type(machine.current), B)

    def test_works_on_a_class_that_already_subclasses_state(self):
        @state
        class Root:
            pass

        @state(parent=Root)
        class Child(State):
            pass

        self.assertIs(Child.parent, Root)
        self.assertTrue(issubclass(Child, State))


class EventDecoratorTests(unittest.TestCase):
    def test_bare_decorator_declares_an_event_subclass(self):
        @event
        class Ping:
            pass

        self.assertTrue(issubclass(Ping, Event))

    def test_decorator_preserves_a_custom_init(self):
        @event
        class Tick:
            def __init__(self, elapsed: float):
                self.elapsed = elapsed

        tick = Tick(2.5)
        self.assertIsInstance(tick, Event)
        self.assertEqual(tick.elapsed, 2.5)

    def test_parent_kwarg_builds_an_event_hierarchy(self):
        @event
        class NetworkEvent:
            pass

        @event(parent=NetworkEvent)
        class Connected:
            pass

        self.assertTrue(issubclass(Connected, NetworkEvent))
        self.assertTrue(issubclass(Connected, Event))

    def test_works_on_a_class_that_already_subclasses_event(self):
        @event
        class Ping(Event):
            pass

        self.assertTrue(issubclass(Ping, Event))

    def test_decorated_event_works_with_transitions_and_isinstance_hierarchy(self):
        @event
        class NetworkEvent:
            pass

        @event(parent=NetworkEvent)
        class Connected:
            pass

        @state
        class Root:
            pass

        @state(parent=Root, initial=True)
        class A:
            pass

        @state(parent=Root)
        class B:
            pass

        # transition keyed on the parent event type catches the subclass
        A.add_transition(NetworkEvent, B)

        machine = StateMachine(Root)
        machine.dispatch(Connected())
        self.assertIs(type(machine.current), B)


class AddTransitionTests(unittest.TestCase):
    def test_add_transition_appends_to_the_transitions_table(self):
        class A(State):
            pass

        class B(State):
            pass

        A.add_transition(Go, B)
        A.add_transition(Back, B, guard="always")

        self.assertEqual(
            A.transitions,
            (Transition(Go, B), Transition(Back, B, guard="always")),
        )

    def test_transitions_added_via_add_transition_are_dispatchable(self):
        class A(State):
            pass

        class B(State):
            pass

        A.add_transition(Go, B)

        machine = StateMachine(A)
        machine.dispatch(Go())

        self.assertIs(type(machine.current), B)


class FlatMachineTests(unittest.TestCase):
    def test_construction_enters_starting_state_with_initialize_event(self):
        log = Log()
        A, B = make_flat(log)
        received: list[Event] = []
        A.on_entered = lambda self, machine, event: received.append(event)

        StateMachine(A)

        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0], Initialize)

    def test_dispatch_transitions_and_calls_hooks_in_order(self):
        log = Log()
        A, B = make_flat(log)
        machine = StateMachine(A)

        self.assertIs(type(machine.current), A)
        self.assertEqual(log.events, ["enter:A"])

        machine.dispatch(Go())
        self.assertIs(type(machine.current), B)
        self.assertEqual(log.events, ["enter:A", "exit:A", "enter:B"])

        machine.dispatch(Back())
        self.assertIs(type(machine.current), A)
        self.assertEqual(
            log.events, ["enter:A", "exit:A", "enter:B", "exit:B", "enter:A"]
        )

    def test_unhandled_event_is_a_no_op(self):
        log = Log()
        A, B = make_flat(log)
        machine = StateMachine(A)
        log.events.clear()

        machine.dispatch(Back())  # A has no transition for Back

        self.assertIs(type(machine.current), A)
        self.assertEqual(log.events, [])


# --- nested / composite machine ----------------------------------------


class NestedState(State):
    log: Log

    def on_entered(self, machine, event):
        self.log.events.append(f"enter:{type(self).__name__}")

    def on_exited(self, machine, event):
        self.log.events.append(f"exit:{type(self).__name__}")


def make_nested(log: Log):
    class NotConnected(NestedState):
        pass

    class Connected(NestedState):
        pass

    class ChargingFromSolar(NestedState):
        parent = Connected

    class Charging(NestedState):
        parent = ChargingFromSolar

    class DipHold(NestedState):
        parent = ChargingFromSolar

        def on_entered(self, machine, event):
            super().on_entered(machine, event)
            self.entered_count = getattr(self, "entered_count", 0) + 1

    Connected.initial = ChargingFromSolar
    ChargingFromSolar.initial = Charging

    NotConnected.transitions = (Transition(Go, Connected),)
    Charging.transitions = (Transition(Go, DipHold),)
    DipHold.transitions = (Transition(Back, Charging), Transition(Go, NotConnected))

    for cls in (NotConnected, Connected, ChargingFromSolar, Charging, DipHold):
        cls.log = log

    return NotConnected, Connected, ChargingFromSolar, Charging, DipHold


class NestedMachineTests(unittest.TestCase):
    def test_initial_chain_descends_to_leaf_on_entry(self):
        log = Log()
        NotConnected, *_ = make_nested(log)
        machine = StateMachine(NotConnected)

        self.assertIs(type(machine.current), NotConnected)
        self.assertEqual(log.events, ["enter:NotConnected"])

    def test_transition_into_composite_descends_through_initial(self):
        log = Log()
        NotConnected, Connected, ChargingFromSolar, Charging, DipHold = make_nested(
            log
        )
        machine = StateMachine(NotConnected)
        log.events.clear()

        machine.dispatch(Go())

        self.assertIs(type(machine.current), Charging)
        self.assertEqual(
            log.events,
            ["exit:NotConnected", "enter:Connected", "enter:ChargingFromSolar", "enter:Charging"],
        )

    def test_transition_between_nested_leaves_shares_lca(self):
        log = Log()
        NotConnected, Connected, ChargingFromSolar, Charging, DipHold = make_nested(
            log
        )
        machine = StateMachine(NotConnected)
        machine.dispatch(Go())  # -> Charging
        log.events.clear()

        machine.dispatch(Go())  # Charging -> DipHold, LCA = ChargingFromSolar

        self.assertIs(type(machine.current), DipHold)
        self.assertEqual(log.events, ["exit:Charging", "enter:DipHold"])

    def test_singleton_instance_persists_state_across_reentry(self):
        log = Log()
        NotConnected, Connected, ChargingFromSolar, Charging, DipHold = make_nested(
            log
        )
        machine = StateMachine(NotConnected)
        machine.dispatch(Go())  # -> Charging
        machine.dispatch(Go())  # -> DipHold (1st visit)
        first_diphold = machine.current
        self.assertEqual(first_diphold.entered_count, 1)

        machine.dispatch(Back())  # -> Charging
        machine.dispatch(Go())  # -> DipHold (2nd visit)

        self.assertIs(machine.current, first_diphold)
        self.assertEqual(first_diphold.entered_count, 2)


# --- event bubbling on a dedicated composite parent handler -------------


class BubbleTests(unittest.TestCase):
    def test_parent_on_event_handles_what_child_does_not(self):
        log = Log()

        class Root(NestedState):
            pass

        class Child(NestedState):
            parent = Root

        class Sibling(NestedState):
            parent = Root

        Root.transitions = (Transition(Go, Sibling),)
        Root.initial = Child

        for cls in (Root, Child, Sibling):
            cls.log = log

        machine = StateMachine(Root)
        self.assertIs(type(machine.current), Child)

        # Child has no transitions of its own; Go must bubble to Root.
        machine.dispatch(Go())
        self.assertIs(type(machine.current), Sibling)


# --- guard-carrying custom on_event override -----------------------------


class GuardTests(unittest.TestCase):
    def test_custom_on_event_override_with_conditional_logic(self):
        log = Log()

        class Idle(NestedState):
            pass

        class Above(NestedState):
            pass

        class Below(NestedState):
            transitions = (Transition(TickWithCount, Above, guard="n >= 3"),)

            def on_event(self, machine, event):
                if isinstance(event, TickWithCount) and event.n >= 3:
                    return Above
                return None

        Idle.transitions = (Transition(Go, Below),)

        for cls in (Idle, Above, Below):
            cls.log = log

        machine = StateMachine(Idle)
        machine.dispatch(Go())
        self.assertIs(type(machine.current), Below)

        machine.dispatch(TickWithCount(1))
        self.assertIs(type(machine.current), Below)  # guard fails, no transition

        machine.dispatch(TickWithCount(3))
        self.assertIs(type(machine.current), Above)  # guard passes


# --- dispatch(EventClass, *args, **kwargs) -------------------------------


class DispatchEventArgsTests(unittest.TestCase):
    def test_dispatch_accepts_event_class_with_positional_args(self):
        log = Log()

        class Idle(NestedState):
            pass

        class Above(NestedState):
            pass

        Idle.transitions = (Transition(TickWithCount, Above),)

        for cls in (Idle, Above):
            cls.log = log

        machine = StateMachine(Idle)
        machine.dispatch(TickWithCount, 3)
        self.assertIs(type(machine.current), Above)

    def test_dispatch_accepts_event_class_with_keyword_args(self):
        log = Log()

        class Idle(NestedState):
            def on_event(self, machine, event):
                if isinstance(event, TickWithCount) and event.n >= 3:
                    return Above
                return None

        class Above(NestedState):
            pass

        Idle.transitions = (Transition(TickWithCount, Above, guard="n >= 3"),)

        for cls in (Idle, Above):
            cls.log = log

        machine = StateMachine(Idle)
        machine.dispatch(TickWithCount, n=1)
        self.assertIs(type(machine.current), Idle)  # guard fails, no transition

        machine.dispatch(TickWithCount, n=3)
        self.assertIs(type(machine.current), Above)  # guard passes

    def test_dispatch_still_accepts_event_instance(self):
        log = Log()

        class Idle(NestedState):
            pass

        class Above(NestedState):
            pass

        Idle.transitions = (Transition(Go, Above),)

        for cls in (Idle, Above):
            cls.log = log

        machine = StateMachine(Idle)
        machine.dispatch(Go())
        self.assertIs(type(machine.current), Above)


if __name__ == "__main__":
    unittest.main()
