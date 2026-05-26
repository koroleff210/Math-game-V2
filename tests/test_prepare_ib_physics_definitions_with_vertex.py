import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.prepare_ib_physics_definitions_with_vertex import (  # noqa: E402
    SourceDefinition,
    calibrate_atomic_task_confidence,
    discover_sources,
    extract_json_from_text,
    fallback_no_vertex,
    is_compound_phrase,
    run_conversion,
    validate_atomic_task,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class PrepareDefinitionsWithVertexTests(unittest.TestCase):
    def test_extract_json_plain_and_markdown(self) -> None:
        self.assertEqual(extract_json_from_text('{"a":1}')["a"], 1)
        self.assertEqual(extract_json_from_text("```json\n{\"a\":2}\n```")["a"], 2)

    def test_discovery_detects_sample_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root / "docs" / "ib_taxonomy.json",
                json.dumps(
                    {
                        "topics": [
                            {
                                "topic_code": "A",
                                "topic_title": "Space, time and motion",
                                "subtopics": [{"subtopic_code": "A.1", "subtopic_title": "Kinematics"}],
                            }
                        ]
                    }
                ),
            )
            _write(
                root / "Analysis" / "exports" / "definitions_bank.csv",
                "subtopic,title,item,kind,syllabus_level,include_in_sl,include_in_hl,ib_style_asks,expected_statement,source_status,review_status,verified_prompt_types,verification_note,paper1_examples,paper2_examples\n"
                "A.1,Kinematics,acceleration,definition,SL,true,true,yes,rate of change of velocity,ok,ok,text_input,note,,\n",
            )
            _write(
                root / "data" / "definitions_extension_bank.csv",
                "definition_id,term,accepted_answers,definition,topic_code,subtopic_code,subtopic_label,level,difficulty,source,active,notes,tags\n"
                "defext_A1_001,deceleration,deceleration,rate of decrease of velocity,A,A.1,Kinematics,extension,medium,dp_syllabus,true,,\n",
            )
            d = discover_sources(root)
            self.assertEqual(len(d["core"]), 1)
            self.assertEqual(len(d["extension"]), 1)

    def test_compound_detection(self) -> None:
        self.assertTrue(is_compound_phrase("speed and velocity"))
        self.assertTrue(is_compound_phrase("mass/weight"))
        self.assertFalse(is_compound_phrase("electric current"))

    def test_no_vertex_fallback_skips_compound_term(self) -> None:
        src = SourceDefinition(
            source_id="defcore_A1_001",
            source_path="x",
            source_term="distance and displacement",
            source_definition="Distance is path length; displacement is change in position.",
            source_topic_code="A",
            source_subtopic_code="A.1",
            source_topic_title="Space, time and motion",
            source_subtopic_title="Kinematics",
        )
        payload = fallback_no_vertex(src)
        self.assertEqual(payload["atomic_tasks"], [])
        self.assertTrue(payload["source_warnings"])

    def test_validate_atomic_task_rejects_compound_expected_and_accepted(self) -> None:
        task = {
            "expected_answer": "speed and velocity",
            "prompt": "Which terms are defined as ...?",
            "content_kind": "definition",
            "answer_type": "text_input",
            "confidence": "high",
            "accepted_answers": ["speed and velocity"],
        }
        issues = validate_atomic_task(task, "a definition")
        self.assertTrue(any("expected_answer is compound" in i for i in issues))
        self.assertTrue(any("accepted_answers contains compound" in i for i in issues))
    
    def test_validate_atomic_task_does_not_false_flag_elastic_collision_prompt(self) -> None:
        task = {
            "expected_answer": "elastic collision",
            "prompt": "Which type of collision is defined as a collision in which total kinetic energy is conserved?",
            "content_kind": "definition",
            "answer_type": "text_input",
            "confidence": "high",
            "accepted_answers": ["elastic collision"],
        }
        issues = validate_atomic_task(task, "collision in which total kinetic energy is conserved")
        self.assertFalse(any("prompt may imply multiple expected answers." in i for i in issues))

    def test_confidence_calibration_explicit_term_becomes_high(self) -> None:
        task = {
            "expected_answer": "acceleration",
            "accepted_answers": [],
            "warnings": [],
            "needs_review": False,
            "confidence": "low",
            "model_confidence": "low",
        }
        calibrated = calibrate_atomic_task_confidence(
            task,
            source_term="acceleration",
            source_warnings=[],
            validation_issues=[],
            source_has_compound_split=False,
        )
        self.assertEqual(calibrated["confidence"], "high")
        self.assertEqual(calibrated["accepted_answers"], ["acceleration"])

    def test_confidence_calibration_compound_split_becomes_medium(self) -> None:
        task = {
            "expected_answer": "distance",
            "accepted_answers": ["distance"],
            "warnings": [],
            "needs_review": False,
            "confidence": "low",
            "model_confidence": "low",
        }
        calibrated = calibrate_atomic_task_confidence(
            task,
            source_term="distance and displacement",
            source_warnings=[],
            validation_issues=[],
            source_has_compound_split=True,
        )
        self.assertEqual(calibrated["confidence"], "medium")

    def test_confidence_calibration_warning_forces_needs_review(self) -> None:
        task = {
            "expected_answer": "elastic collision",
            "accepted_answers": ["elastic collision"],
            "warnings": ["prompt may imply multiple expected answers."],
            "needs_review": False,
            "confidence": "high",
            "model_confidence": "high",
        }
        calibrated = calibrate_atomic_task_confidence(
            task,
            source_term="elastic collision",
            source_warnings=[],
            validation_issues=[],
            source_has_compound_split=False,
        )
        self.assertEqual(calibrated["confidence"], "low")
        self.assertTrue(calibrated["needs_review"])

    def test_confidence_calibration_validation_failure_forces_low(self) -> None:
        task = {
            "expected_answer": "mass",
            "accepted_answers": ["mass"],
            "warnings": [],
            "needs_review": False,
            "confidence": "high",
            "model_confidence": "high",
        }
        calibrated = calibrate_atomic_task_confidence(
            task,
            source_term="mass",
            source_warnings=[],
            validation_issues=["some validation failure"],
            source_has_compound_split=False,
        )
        self.assertEqual(calibrated["confidence"], "low")
        self.assertTrue(calibrated["needs_review"])

    def test_from_raw_flatten_preserves_source_and_atomic_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            out_dir = tmp / "out"
            source = SourceDefinition(
                source_id="defcore_A1_010",
                source_path="p",
                source_term="acceleration",
                source_definition="rate of change of velocity",
                source_topic_code="A",
                source_subtopic_code="A.1",
                source_topic_title="Space, time and motion",
                source_subtopic_title="Kinematics",
            )
            raw = [
                {
                    "source_id": source.source_id,
                    "source_path": source.source_path,
                    "parsed_json": {
                        "source_id": source.source_id,
                        "source_path": source.source_path,
                        "source_term": "acceleration",
                        "source_definition": source.source_definition,
                        "source_topic_code": "A",
                        "source_subtopic_code": "A.1",
                        "source_topic_title": source.source_topic_title,
                        "source_subtopic_title": source.source_subtopic_title,
                        "source_warnings": [],
                        "atomic_tasks": [
                            {
                                "atomic_id": "a1",
                                "content_kind": "definition",
                                "answer_type": "text_input",
                                "prompt": "Which physical quantity is defined as: \"rate of change of velocity\"?",
                                "expected_answer": "acceleration",
                                "accepted_answers": ["acceleration"],
                                "answer_symbols": ["a"],
                                "confidence": "high",
                                "needs_review": False,
                                "warnings": [],
                            }
                        ],
                    },
                    "api_or_parsing_error": "",
                }
            ]
            raw_path = out_dir / "definitions_vertex_raw.jsonl"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text("\n".join(json.dumps(r) for r in raw), encoding="utf-8")

            class Args:
                from_raw = True
                raw_input = raw_path
                output_dir = out_dir
                no_vertex = True
                model = "mock"
                max_retries = 1
                dry_run = True

            run_conversion(Args, [source])
            converted = json.loads((out_dir / "definitions_converted.json").read_text(encoding="utf-8"))
            self.assertEqual(len(converted), 1)
            self.assertEqual(converted[0]["source_id"], source.source_id)
            self.assertEqual(converted[0]["atomic_id"], "a1")
            self.assertEqual(converted[0]["model_confidence"], "high")


if __name__ == "__main__":
    unittest.main()
