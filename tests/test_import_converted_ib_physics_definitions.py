import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.problems import (
    PROBLEM_ANSWER_TYPE_TEXT_INPUT,
    PROBLEM_CONTENT_KIND_DEFINITION,
    Problem,
    ProblemAcceptedAnswer,
    ProblemBlock,
    ProblemSet,
    ProblemSourceMetadata,
    Topic,
)
from app.models.subjects import Subject
from tools.import_converted_ib_physics_definitions import (
    SOURCE_SYSTEM,
    build_topic_mapping,
    classify_rows,
    import_candidates,
)


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "definitions-importer-test-secret"
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = "threading"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


class ImportConvertedDefinitionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = create_app(_TestConfig)

    def setUp(self) -> None:
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        subject = Subject(name="IB DP Physics")
        db.session.add(subject)
        db.session.flush()
        db.session.add_all(
            [
                Topic(name="A1 - Kinematics", subject_id=subject.id),
                Topic(name="A2 - Forces and Momentum", subject_id=subject.id),
            ]
        )
        db.session.commit()
        self.subject = subject

    def tearDown(self) -> None:
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _row(self, **overrides):
        base = {
            "source_id": "defcore_A1_001",
            "atomic_id": "defcore_A1_001__a1",
            "source_term": "acceleration",
            "source_definition": "rate of change of velocity",
            "source_topic_code": "A",
            "source_subtopic_code": "A.1",
            "source_topic_title": "Space, time and motion",
            "source_subtopic_title": "Kinematics",
            "content_kind": "definition",
            "answer_type": "text_input",
            "title": "Definition: acceleration",
            "prompt": "Which physical quantity is defined as: \"rate of change of velocity\"?",
            "expected_answer": "acceleration",
            "accepted_answers": ["acceleration"],
            "model_confidence": "high",
            "confidence": "high",
            "needs_review": False,
            "warnings": [],
            "source_warnings": [],
            "difficulty": 1,
        }
        base.update(overrides)
        return base

    def test_classify_rows_only_clean_and_skip_duplicates(self) -> None:
        mapping, _ = build_topic_mapping(self.subject)
        rows = [
            self._row(atomic_id="a1", expected_answer="displacement"),
            self._row(atomic_id="a2", expected_answer="displacement"),
            self._row(atomic_id="a3", confidence="medium"),
            self._row(atomic_id="a4", needs_review=True),
            self._row(atomic_id="a5", warnings=["prompt may imply multiple expected answers."]),
            self._row(atomic_id="a6", expected_answer="speed and velocity"),
        ]
        selected, reasons, _ = classify_rows(
            rows,
            topic_by_code=mapping,
            include_duplicates=False,
            allow_medium=False,
            limit=0,
        )
        self.assertEqual(len(selected), 0)
        self.assertGreaterEqual(reasons["duplicate_expected_within_subtopic"], 2)
        self.assertEqual(reasons["confidence_medium"], 1)
        self.assertEqual(reasons["needs_review_true"], 1)
        self.assertEqual(reasons["validation_failure"], 1)
        self.assertEqual(reasons["compound_expected_answer"], 1)

    def test_import_candidates_creates_definition_problem_blocks_answers_and_metadata(self) -> None:
        mapping, _ = build_topic_mapping(self.subject)
        row = self._row()
        selected, reasons, _ = classify_rows(
            [row],
            topic_by_code=mapping,
            include_duplicates=False,
            allow_medium=False,
            limit=0,
        )
        self.assertEqual(dict(reasons), {})
        out = import_candidates(selected, Path("instance/definition_import_preview_full_vertex"))
        self.assertEqual(out["imported_count"], 1)
        problem = Problem.query.one()
        self.assertEqual(problem.content_kind, PROBLEM_CONTENT_KIND_DEFINITION)
        self.assertEqual(problem.answer_type, PROBLEM_ANSWER_TYPE_TEXT_INPUT)
        self.assertEqual(ProblemBlock.query.count(), 1)
        self.assertEqual(ProblemAcceptedAnswer.query.count(), 1)
        self.assertEqual(ProblemSet.query.count(), 0)
        metadata = ProblemSourceMetadata.query.one()
        self.assertEqual(metadata.source_system, SOURCE_SYSTEM)
        self.assertEqual(metadata.source_id, "defcore_A1_001")
        self.assertIn("atomic_id", metadata.raw_metadata_json)


if __name__ == "__main__":
    unittest.main()
