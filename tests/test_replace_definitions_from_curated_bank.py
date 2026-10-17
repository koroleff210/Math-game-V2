import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.replace_definitions_from_curated_bank import (  # noqa: E402
    as_list_of_str,
    definition_statement_text,
)


class ReplaceDefinitionsFromCuratedBankTests(unittest.TestCase):
    def test_definition_statement_text_uses_definition_not_question_wrapper(self) -> None:
        row = {
            "definition_text": "rate of change of velocity",
            "prompt": "Which physics term is defined as: \"rate of change of velocity\"?",
        }
        self.assertEqual(definition_statement_text(row), "Rate of change of velocity")

    def test_as_list_of_str_splits_semicolon_values(self) -> None:
        values = as_list_of_str("potential difference; voltage; p.d.; pd")
        self.assertEqual(values, ["potential difference", "voltage", "p.d.", "pd"])


if __name__ == "__main__":
    unittest.main()
