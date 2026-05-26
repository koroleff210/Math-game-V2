from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.game import GameSession  # noqa: E402
from app.models.problems import (  # noqa: E402
    PROBLEM_ANSWER_TYPE_TEXT_INPUT,
    PROBLEM_BLOCK_TYPE_RICH_TEXT,
    PROBLEM_CONTENT_KIND_DEFINITION,
    Problem,
    ProblemAcceptedAnswer,
    ProblemBlock,
    ProblemSet,
    ProblemSourceMetadata,
    Topic,
)
from app.models.subjects import Subject  # noqa: E402


SUBJECT_NAME = "IB DP Physics"
SOURCE_SYSTEM = "ib_physics_definitions_vertex"
DEFAULT_INPUT_DIR = PROJECT_ROOT / "instance" / "definition_import_preview_full_vertex"
CONVERTED_JSONL_NAME = "definitions_converted.jsonl"
EXPECTED_CLEAN_COUNT = 159
VALIDATION_MARKERS = (
    "expected_answer is missing.",
    "expected_answer is compound and invalid",
    "prompt is missing.",
    "prompt may imply multiple expected answers.",
    'content_kind must be "definition".',
    'answer_type must be "text_input".',
    "confidence must be high|medium|low.",
    "accepted_answers must be non-empty for high/medium confidence.",
    "accepted_answers contains compound value:",
    "accepted answer appears too long:",
)


@dataclass
class ImportCandidate:
    row: dict[str, Any]
    canonical_id: str
    topic_id: int
    accepted_answers: list[str]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import only clean converted IB Physics definitions.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--only-clean", action="store_true", default=True)
    parser.add_argument("--allow-medium", action="store_true")
    parser.add_argument("--include-duplicates", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run and args.write:
        raise SystemExit("Choose either --dry-run or --write, not both.")
    if not args.dry_run and not args.write:
        args.dry_run = True
    return args


def normalize_space(value: object) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def norm_casefold(value: object) -> str:
    return normalize_space(value).casefold()


def is_compound_phrase(text: str) -> bool:
    t = norm_casefold(text)
    return any(sep in t for sep in (" and ", " or ", "/", ",", ";"))


def as_list_of_str(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [normalize_space(v) for v in value if normalize_space(v)]
    scalar = normalize_space(value)
    return [scalar] if scalar else []


def load_converted_rows(input_dir: Path) -> list[dict[str, Any]]:
    path = input_dir / CONVERTED_JSONL_NAME
    if not path.exists():
        raise SystemExit(f"Missing converted file: {path}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def canonical_id_for(row: dict[str, Any]) -> str:
    source_id = normalize_space(row.get("source_id", ""))
    atomic_id = normalize_space(row.get("atomic_id", ""))
    return f"def::{source_id}::{atomic_id}"


def has_validation_failure(row: dict[str, Any]) -> bool:
    warnings = as_list_of_str(row.get("warnings"))
    for warning in warnings:
        if any(warning.startswith(marker) for marker in VALIDATION_MARKERS):
            return True
    return False


def topic_code_from_name(name: str) -> str | None:
    normalized = normalize_space(name).upper()
    match = re.search(r"\b([A-E])\s*\.?\s*([1-5])\b", normalized)
    if not match:
        return None
    return f"{match.group(1)}.{match.group(2)}"


def build_topic_mapping(subject: Subject) -> tuple[dict[str, Topic], list[str]]:
    mapping: dict[str, Topic] = {}
    collisions: list[str] = []
    for topic in subject.topics.all():
        code = topic_code_from_name(topic.name)
        if not code:
            continue
        if code in mapping and mapping[code].id != topic.id:
            collisions.append(f"{code}: topic ids {mapping[code].id} and {topic.id}")
            continue
        mapping[code] = topic
    return mapping, collisions


def normalize_accepted_answers(row: dict[str, Any]) -> list[str]:
    expected = normalize_space(row.get("expected_answer", ""))
    accepted = as_list_of_str(row.get("accepted_answers"))
    if not accepted and expected and not is_compound_phrase(expected):
        accepted = [expected]
    deduped: list[str] = []
    seen: set[str] = set()
    for answer in accepted:
        key = norm_casefold(answer)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(answer)
    return deduped


def accepted_answers_safe(row: dict[str, Any], accepted: list[str]) -> bool:
    definition_words = len(normalize_space(row.get("source_definition", "")).split())
    for answer in accepted:
        if is_compound_phrase(answer):
            return False
        if len(answer.split()) >= max(12, definition_words):
            return False
    return True


def db_counts() -> dict[str, Any]:
    content_kind_rows = (
        db.session.query(Problem.content_kind, db.func.count(Problem.id))
        .group_by(Problem.content_kind)
        .all()
    )
    return {
        "subject": Subject.query.count(),
        "topic": Topic.query.count(),
        "problem": Problem.query.count(),
        "problem_set": ProblemSet.query.count(),
        "problem_block": ProblemBlock.query.count(),
        "problem_accepted_answer": ProblemAcceptedAnswer.query.count(),
        "problem_source_metadata": ProblemSourceMetadata.query.count(),
        "content_kind_distribution": {k: int(v) for k, v in content_kind_rows},
    }


def active_waiting_session_count() -> int:
    return (
        GameSession.query.filter(GameSession.status.in_(["active", "waiting"])).count()
    )


def classify_rows(
    rows: list[dict[str, Any]],
    *,
    topic_by_code: dict[str, Topic],
    include_duplicates: bool,
    allow_medium: bool,
    limit: int,
) -> tuple[list[ImportCandidate], Counter, dict[tuple[str, str], int]]:
    pair_counts = Counter(
        (
            normalize_space(row.get("source_subtopic_code", "")),
            norm_casefold(row.get("expected_answer", "")),
        )
        for row in rows
        if normalize_space(row.get("source_subtopic_code", "")) and normalize_space(row.get("expected_answer", ""))
    )
    skip_reasons = Counter()
    selected: list[ImportCandidate] = []

    for row in rows:
        content_kind = norm_casefold(row.get("content_kind", ""))
        answer_type = norm_casefold(row.get("answer_type", ""))
        confidence = norm_casefold(row.get("confidence", ""))
        needs_review = bool(row.get("needs_review"))
        expected = normalize_space(row.get("expected_answer", ""))
        subtopic = normalize_space(row.get("source_subtopic_code", ""))
        topic = normalize_space(row.get("source_topic_code", ""))
        accepted = normalize_accepted_answers(row)
        pair = (subtopic, norm_casefold(expected))

        if content_kind != PROBLEM_CONTENT_KIND_DEFINITION:
            skip_reasons["content_kind_not_definition"] += 1
            continue
        if answer_type != PROBLEM_ANSWER_TYPE_TEXT_INPUT:
            skip_reasons["answer_type_not_text_input"] += 1
            continue
        if confidence == "medium" and not allow_medium:
            skip_reasons["confidence_medium"] += 1
            continue
        if confidence == "low":
            skip_reasons["confidence_low"] += 1
            continue
        if confidence not in {"high", "medium"}:
            skip_reasons["confidence_invalid"] += 1
            continue
        if needs_review:
            skip_reasons["needs_review_true"] += 1
            continue
        if has_validation_failure(row):
            skip_reasons["validation_failure"] += 1
            continue
        if not subtopic or not topic:
            skip_reasons["missing_topic_or_subtopic"] += 1
            continue
        if subtopic not in topic_by_code:
            skip_reasons["topic_mapping_missing"] += 1
            continue
        if not expected:
            skip_reasons["missing_expected_answer"] += 1
            continue
        if is_compound_phrase(expected):
            skip_reasons["compound_expected_answer"] += 1
            continue
        if not accepted:
            skip_reasons["accepted_answers_missing"] += 1
            continue
        if not accepted_answers_safe(row, accepted):
            skip_reasons["accepted_answers_unsafe"] += 1
            continue
        if pair_counts[pair] > 1 and not include_duplicates:
            skip_reasons["duplicate_expected_within_subtopic"] += 1
            continue

        selected.append(
            ImportCandidate(
                row=row,
                canonical_id=canonical_id_for(row),
                topic_id=topic_by_code[subtopic].id,
                accepted_answers=accepted,
            )
        )

    if limit > 0:
        selected = selected[:limit]
    return selected, skip_reasons, pair_counts


def existing_canonical_ids() -> set[str]:
    rows = ProblemSourceMetadata.query.filter_by(source_system=SOURCE_SYSTEM).all()
    return {row.canonical_id for row in rows}


def import_candidates(candidates: list[ImportCandidate], input_dir: Path) -> dict[str, Any]:
    import_batch_id = uuid.uuid4().hex
    imported_ids: list[int] = []
    imported_subtopics = Counter()
    existing = existing_canonical_ids()

    for candidate in candidates:
        if candidate.canonical_id in existing:
            continue
        row = candidate.row
        prompt = normalize_space(row.get("prompt", ""))
        title = normalize_space(row.get("title", "")) or f"Definition: {normalize_space(row.get('expected_answer', ''))}"
        difficulty = row.get("difficulty")
        if not isinstance(difficulty, int):
            difficulty = 1

        problem = Problem(
            topic_id=candidate.topic_id,
            title=title,
            prompt_text=prompt,
            answer_text=candidate.accepted_answers[0],
            answer_type=PROBLEM_ANSWER_TYPE_TEXT_INPUT,
            content_kind=PROBLEM_CONTENT_KIND_DEFINITION,
            difficulty=difficulty,
        )
        db.session.add(problem)
        db.session.flush()

        db.session.add(
            ProblemBlock(
                problem_id=problem.id,
                position=1,
                block_type=PROBLEM_BLOCK_TYPE_RICH_TEXT,
                text_content=prompt,
            )
        )
        for idx, answer in enumerate(candidate.accepted_answers, start=1):
            db.session.add(
                ProblemAcceptedAnswer(
                    problem_id=problem.id,
                    position=idx,
                    answer_text=answer,
                )
            )

        metadata_payload = {
            "source_id": row.get("source_id"),
            "atomic_id": row.get("atomic_id"),
            "source_term": row.get("source_term"),
            "source_definition": row.get("source_definition"),
            "source_topic_code": row.get("source_topic_code"),
            "source_subtopic_code": row.get("source_subtopic_code"),
            "source_topic_title": row.get("source_topic_title"),
            "source_subtopic_title": row.get("source_subtopic_title"),
            "model_confidence": row.get("model_confidence"),
            "confidence": row.get("confidence"),
            "warnings": row.get("warnings"),
            "source_warnings": row.get("source_warnings"),
            "conversion_input_dir": str(input_dir),
        }
        db.session.add(
            ProblemSourceMetadata(
                problem_id=problem.id,
                source_system=SOURCE_SYSTEM,
                source_bank_path=str(input_dir / CONVERTED_JSONL_NAME),
                source_id=normalize_space(row.get("source_id", "")),
                canonical_id=candidate.canonical_id,
                content_hash=hashlib.sha1(normalize_space(prompt).encode("utf-8")).hexdigest(),
                answer_hash=hashlib.sha1("|".join(candidate.accepted_answers).encode("utf-8")).hexdigest(),
                import_batch_id=import_batch_id,
                raw_metadata_json=metadata_payload,
            )
        )
        imported_ids.append(problem.id)
        imported_subtopics[normalize_space(row.get("source_subtopic_code", ""))] += 1
        existing.add(candidate.canonical_id)

    db.session.commit()
    return {
        "import_batch_id": import_batch_id,
        "problem_ids": imported_ids,
        "imported_count": len(imported_ids),
        "imported_subtopic_distribution": dict(imported_subtopics),
    }


def report_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = create_app()
    with app.app_context():
        before = db_counts()
        active_waiting = active_waiting_session_count()
        if active_waiting > 0:
            report_json(
                {
                    "ok": False,
                    "reason": "active_or_waiting_sessions_present",
                    "active_or_waiting_sessions": active_waiting,
                }
            )
            return 2

        subject = Subject.query.filter_by(name=SUBJECT_NAME).first()
        if not subject:
            report_json({"ok": False, "reason": f"subject_not_found:{SUBJECT_NAME}"})
            return 2

        topic_by_code, collisions = build_topic_mapping(subject)
        rows = load_converted_rows(args.input_dir.resolve())
        candidates, skip_reasons, pair_counts = classify_rows(
            rows,
            topic_by_code=topic_by_code,
            include_duplicates=args.include_duplicates,
            allow_medium=args.allow_medium,
            limit=args.limit,
        )
        duplicate_groups = [
            {"subtopic": subtopic, "expected_answer": expected, "count": count}
            for (subtopic, expected), count in pair_counts.items()
            if subtopic and expected and count > 1
        ]
        mismatch = len(candidates) != EXPECTED_CLEAN_COUNT

        summary = {
            "ok": True,
            "mode": "write" if args.write else "dry_run",
            "input_dir": str(args.input_dir.resolve()),
            "pre_import_counts": before,
            "active_or_waiting_sessions": active_waiting,
            "subject_id": subject.id,
            "topic_mapping_count": len(topic_by_code),
            "topic_mapping_collisions": collisions,
            "total_rows": len(rows),
            "importable_clean_count": len(candidates),
            "expected_clean_count": EXPECTED_CLEAN_COUNT,
            "count_mismatch": mismatch,
            "skip_reasons": dict(skip_reasons),
            "duplicate_group_count": len(duplicate_groups),
            "duplicate_groups_examples": duplicate_groups[:20],
        }

        if args.write:
            if mismatch:
                report_json(
                    {
                        **summary,
                        "ok": False,
                        "reason": "importable_count_mismatch",
                    }
                )
                return 2
            result = import_candidates(candidates, args.input_dir.resolve())
            after = db_counts()
            summary.update(
                {
                    "write_result": result,
                    "post_import_counts": after,
                }
            )
            report_json(summary)
            return 0

        report_json(summary)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
