import unittest

from statemachine.core import Event, State, Transition
from statemachine.plantuml import generate_plantuml


class Go(Event):
    pass


class Back(Event):
    pass


class FlatPlantumlTests(unittest.TestCase):
    def test_sibling_leaves_under_a_single_root_have_no_extra_nesting(self):
        class Root(State):
            pass

        class A(State):
            parent = Root

        class B(State):
            parent = Root

        Root.initial = A
        A.transitions = (Transition(Go, B),)
        B.transitions = (Transition(Back, A, guard="always"),)

        output = generate_plantuml(Root)
        stripped_lines = [line.strip() for line in output.splitlines()]

        self.assertIn("@startuml", output)
        self.assertIn("@enduml", output)
        self.assertIn("state Root {", stripped_lines)
        self.assertIn("state A", stripped_lines)
        self.assertIn("state B", stripped_lines)
        self.assertIn("A --> B : Go", stripped_lines)
        self.assertIn("B --> A : Back [always]", stripped_lines)
        self.assertNotIn("state A {", output)
        self.assertNotIn("state B {", output)


class NestedPlantumlTests(unittest.TestCase):
    def test_nested_machine_emits_composite_blocks_and_initial_chain(self):
        class Connected(State):
            pass

        class ChargingFromSolar(State):
            parent = Connected

        class Charging(State):
            parent = ChargingFromSolar

        class DipHold(State):
            parent = ChargingFromSolar

        Connected.initial = ChargingFromSolar
        ChargingFromSolar.initial = Charging
        Charging.transitions = (
            Transition(Go, DipHold, guard="surplus below threshold"),
        )
        DipHold.transitions = (Transition(Back, Charging),)

        output = generate_plantuml(Connected)
        stripped_lines = [line.strip() for line in output.splitlines()]

        self.assertIn("state Connected {", stripped_lines)
        self.assertIn("state ChargingFromSolar {", stripped_lines)
        self.assertIn("state Charging", stripped_lines)
        self.assertIn("state DipHold", stripped_lines)
        self.assertIn("[*] --> ChargingFromSolar", stripped_lines)
        self.assertIn("[*] --> Charging", stripped_lines)
        self.assertIn(
            "Charging --> DipHold : Go [surplus below threshold]", stripped_lines
        )
        self.assertIn("DipHold --> Charging : Back", stripped_lines)


if __name__ == "__main__":
    unittest.main()
