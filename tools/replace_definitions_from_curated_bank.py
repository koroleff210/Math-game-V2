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
    problem_set_problems,
)
from app.models.subjects import Subject  # noqa: E402

EXPECTED_CURATED_COUNT = 138
SUBJECT_NAME = "IB DP Physics"
SOURCE_SYSTEM = "ib_physics_definitions_curated_pdf"
COMPOUND_SEPARATORS = (" and ", " or ", "/", ",", ";")


@dataclass
class PreparedRow:
    row: dict[str, Any]
    topic_id: int
    prompt: str
    expected_answer: str
    accepted_answers: list[str]
    canonical_id: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replace imported definition bank with curated PDF-ready definitions.")
    parser.add_argument("--input-file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run and args.write:
        raise SystemExit("Choose either --dry-run or --write.")
    if not args.dry_run and not args.write:
        args.dry_run = True
    return args


def normalize_space(value: object) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def norm_casefold(value: object) -> str:
    return normalize_space(value).casefold()


def is_compound(value: str) -> bool:
    t = norm_casefold(value)
    return any(sep in t for sep in COMPOUND_SEPARATORS)


def as_list_of_str(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [normalize_space(v) for v in value if normalize_space(v)]
    s = normalize_space(value)
    if not s:
        return []
    # Curated sheets may store multiple accepted answers as "a; b; c".
    if ";" in s:
        return [normalize_space(part) for part in re.split(r"\s*;\s*", s) if normalize_space(part)]
    return [s]


def definition_statement_text(row: dict[str, Any]) -> str:
    text = normalize_space(row.get("definition_text", "")) or normalize_space(row.get("source_definition_summary", ""))
    if not text:
        text = normalize_space(row.get("prompt", ""))
    text = text.strip('"')
    if not text:
        return text
    return text[0].upper() + text[1:]


def db_counts() -> dict[str, Any]:
    content_kind = db.session.query(Problem.content_kind, db.func.count(Problem.id)).group_by(Problem.content_kind).all()
    answer_type = db.session.query(Problem.answer_type, db.func.count(Problem.id)).group_by(Problem.answer_type).all()
    return {
        "subject": Subject.query.count(),
        "topic": Topic.query.count(),
        "problem_total": Problem.query.count(),
        "problem_by_content_kind": {k: int(v) for k, v in content_kind},
        "problem_by_answer_type": {k: int(v) for k, v in answer_type},
        "problem_set_total": ProblemSet.query.count(),
        "problem_block": ProblemBlock.query.count(),
        "problem_accepted_answer": ProblemAcceptedAnswer.query.count(),
        "problem_source_metadata": ProblemSourceMetadata.query.count(),
    }


def active_waiting_sessions() -> int:
    return GameSession.query.filter(GameSession.status.in_(["active", "waiting"])).count()


def topic_code_from_name(name: str) -> str | None:
    m = re.search(r"\b([A-E])\s*\.?\s*([1-5])\b", normalize_space(name).upper())
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}"


def build_topic_mapping(subject: Subject) -> dict[str, Topic]:
    mapping: dict[str, Topic] = {}
    for topic in subject.topics.all():
        code = topic_code_from_name(topic.name)
        if code:
            mapping[code] = topic
    return mapping


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"Curated file not found: {path}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


def existing_definition_audit() -> dict[str, Any]:
    defs = Problem.query.filter_by(content_kind=PROBLEM_CONTENT_KIND_DEFINITION).all()
    ids = [p.id for p in defs]
    out: dict[str, Any] = {
        "definition_total": len(defs),
        "answer_type_distribution": {},
        "topic_distribution": {},
        "source_system_distribution": {},
        "definitions_in_problem_sets": 0,
        "definition_problemset_links": [],
        "missing_source_metadata_count": 0,
        "manual_like_count": 0,
    }
    if not defs:
        return out
    out["answer_type_distribution"] = dict(
        db.session.query(Problem.answer_type, db.func.count(Problem.id))
        .filter(Problem.content_kind == PROBLEM_CONTENT_KIND_DEFINITION)
        .group_by(Problem.answer_type)
        .all()
    )
    out["topic_distribution"] = dict(
        db.session.query(Topic.name, db.func.count(Problem.id))
        .join(Problem, Problem.topic_id == Topic.id)
        .filter(Problem.content_kind == PROBLEM_CONTENT_KIND_DEFINITION)
        .group_by(Topic.name)
        .all()
    )
    out["source_system_distribution"] = dict(
        db.session.query(db.func.coalesce(ProblemSourceMetadata.source_system, "<missing>"), db.func.count(Problem.id))
        .select_from(Problem)
        .outerjoin(ProblemSourceMetadata, ProblemSourceMetadata.problem_id == Problem.id)
        .filter(Problem.content_kind == PROBLEM_CONTENT_KIND_DEFINITION)
        .group_by(db.func.coalesce(ProblemSourceMetadata.source_system, "<missing>"))
        .all()
    )
    out["missing_source_metadata_count"] = (
        db.session.query(Problem.id)
        .outerjoin(ProblemSourceMetadata, ProblemSourceMetadata.problem_id == Problem.id)
        .filter(Problem.content_kind == PROBLEM_CONTENT_KIND_DEFINITION, ProblemSourceMetadata.id.is_(None))
        .count()
    )
    out["definitions_in_problem_sets"] = (
        db.session.query(problem_set_problems.c.problem_id)
        .join(Problem, Problem.id == problem_set_problems.c.problem_id)
        .filter(Problem.content_kind == PROBLEM_CONTENT_KIND_DEFINITION)
        .distinct()
        .count()
    )
    out["definition_problemset_links"] = [
        {"problem_set_id": psid, "problem_set_name": psname, "definition_count": cnt}
        for psid, psname, cnt in (
            db.session.query(ProblemSet.id, ProblemSet.name, db.func.count(Problem.id))
            .join(problem_set_problems, problem_set_problems.c.problem_set_id == ProblemSet.id)
            .join(Problem, Problem.id == problem_set_problems.c.problem_id)
            .filter(Problem.content_kind == PROBLEM_CONTENT_KIND_DEFINITION)
            .group_by(ProblemSet.id, ProblemSet.name)
            .all()
        )
    ]
    out["manual_like_count"] = (
        db.session.query(Problem.id)
        .outerjoin(ProblemSourceMetadata, ProblemSourceMetadata.problem_id == Problem.id)
        .filter(
            Problem.content_kind == PROBLEM_CONTENT_KIND_DEFINITION,
            db.or_(
                ProblemSourceMetadata.source_system.is_(None),
                ProblemSourceMetadata.source_system != "ib_physics_definitions_vertex",
            ),
        )
        .count()
    )
    return out


def prepare_rows(rows: list[dict[str, Any]], topic_mapping: dict[str, Topic]) -> tuple[list[PreparedRow], Counter]:
    prepared: list[PreparedRow] = []
    skips = Counter()
    for idx, row in enumerate(rows, start=1):
        content_kind = norm_casefold(row.get("content_kind", ""))
        answer_type = norm_casefold(row.get("answer_type", ""))
        quality = norm_casefold(row.get("quality", ""))
        if content_kind != "definition":
            skips["content_kind_not_definition"] += 1
            continue
        if answer_type != PROBLEM_ANSWER_TYPE_TEXT_INPUT:
            skips["answer_type_not_text_input"] += 1
            continue
        if quality != "import_ready":
            skips["quality_not_import_ready"] += 1
            continue
        code = normalize_space(row.get("ib_subtopic_code", "")).upper().replace(".", "")
        topic = topic_mapping.get(code)
        if not topic:
            skips["topic_mapping_missing"] += 1
            continue
        expected = normalize_space(row.get("expected_answer", ""))
        if not expected:
            skips["missing_expected_answer"] += 1
            continue
        if is_compound(expected):
            skips["compound_expected_answer"] += 1
            continue
        prompt = definition_statement_text(row)
        accepted = as_list_of_str(row.get("accepted_answers"))
        if expected and all(norm_casefold(a) != norm_casefold(expected) for a in accepted):
            accepted.append(expected)
        accepted = [a for a in accepted if a and not is_compound(a)]
        if not accepted:
            skips["accepted_answers_missing_or_invalid"] += 1
            continue
        if any(len(a.split()) >= 12 for a in accepted):
            skips["accepted_answer_too_long"] += 1
            continue
        source_file = normalize_space(row.get("source_file", ""))
        source_term = normalize_space(row.get("source_term", ""))
        source_ref = normalize_space(row.get("source_reference", ""))
        canonical = f"curated::{code}::{norm_casefold(expected)}::{idx}"
        prepared.append(
            PreparedRow(
                row=row,
                topic_id=topic.id,
                prompt=prompt,
                expected_answer=expected,
                accepted_answers=accepted,
                canonical_id=canonical,
            )
        )
    return prepared, skips


def delete_existing_definitions() -> dict[str, int]:
    def_ids = [pid for (pid,) in db.session.query(Problem.id).filter(Problem.content_kind == PROBLEM_CONTENT_KIND_DEFINITION).all()]
    if not def_ids:
        return {"problem": 0, "problem_block": 0, "problem_accepted_answer": 0, "problem_source_metadata": 0, "problem_set_links": 0}
    links = db.session.execute(
        problem_set_problems.delete().where(problem_set_problems.c.problem_id.in_(def_ids))
    ).rowcount
    block = ProblemBlock.query.filter(ProblemBlock.problem_id.in_(def_ids)).delete(synchronize_session=False)
    ans = ProblemAcceptedAnswer.query.filter(ProblemAcceptedAnswer.problem_id.in_(def_ids)).delete(synchronize_session=False)
    meta = ProblemSourceMetadata.query.filter(ProblemSourceMetadata.problem_id.in_(def_ids)).delete(synchronize_session=False)
    prob = Problem.query.filter(Problem.id.in_(def_ids)).delete(synchronize_session=False)
    return {"problem": prob, "problem_block": block, "problem_accepted_answer": ans, "problem_source_metadata": meta, "problem_set_links": links or 0}


def insert_curated(prepared: list[PreparedRow], input_file: Path) -> dict[str, Any]:
    batch = uuid.uuid4().hex
    imported = 0
    subtopic_dist: Counter = Counter()
    for item in prepared:
        row = item.row
        problem = Problem(
            topic_id=item.topic_id,
            title=f"Definition: {item.expected_answer}",
            prompt_text=item.prompt,
            answer_text=item.accepted_answers[0],
            answer_type=PROBLEM_ANSWER_TYPE_TEXT_INPUT,
            content_kind=PROBLEM_CONTENT_KIND_DEFINITION,
            difficulty=1,
        )
        db.session.add(problem)
        db.session.flush()
        db.session.add(
            ProblemBlock(
                problem_id=problem.id,
                position=1,
                block_type=PROBLEM_BLOCK_TYPE_RICH_TEXT,
                text_content=item.prompt,
            )
        )
        for pos, ans in enumerate(item.accepted_answers, start=1):
            db.session.add(
                ProblemAcceptedAnswer(
                    problem_id=problem.id,
                    position=pos,
                    answer_text=ans,
                )
            )
        raw = dict(row)
        raw["canonical_source"] = item.canonical_id
        db.session.add(
            ProblemSourceMetadata(
                problem_id=problem.id,
                source_system=SOURCE_SYSTEM,
                source_bank_path=str(input_file),
                source_id=normalize_space(row.get("source_term", "")) or normalize_space(row.get("expected_answer", "")),
                canonical_id=item.canonical_id,
                content_hash=hashlib.sha1(item.prompt.encode("utf-8")).hexdigest(),
                answer_hash=hashlib.sha1("|".join(item.accepted_answers).encode("utf-8")).hexdigest(),
                import_batch_id=batch,
                raw_metadata_json=raw,
            )
        )
        imported += 1
        subtopic_dist[normalize_space(row.get("ib_subtopic_code", ""))] += 1
    db.session.commit()
    return {"imported_count": imported, "import_batch_id": batch, "subtopic_distribution": dict(subtopic_dist)}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_file = args.input_file.resolve()
    app = create_app()
    with app.app_context():
        pre = db_counts()
        session_open = active_waiting_sessions()
        audit = existing_definition_audit()
        rows = load_rows(input_file)
        if session_open > 0:
            print(json.dumps({"ok": False, "reason": "active_or_waiting_sessions_present", "count": session_open}, indent=2))
            return 2
        if len(rows) != EXPECTED_CURATED_COUNT:
            print(json.dumps(
                {
                    "ok": False,
                    "reason": "curated_count_mismatch",
                    "expected_curated_count": EXPECTED_CURATED_COUNT,
                    "actual_curated_count": len(rows),
                    "pre_counts": pre,
                    "existing_definition_audit": audit,
                },
                ensure_ascii=False,
                indent=2,
            ))
            return 2
        subject = Subject.query.filter_by(name=SUBJECT_NAME).first()
        if not subject:
            print(json.dumps({"ok": False, "reason": "subject_not_found", "subject": SUBJECT_NAME}, indent=2))
            return 2
        mapping = build_topic_mapping(subject)
        prepared, skips = prepare_rows(rows, mapping)
        dry = {
            "ok": True,
            "mode": "dry_run" if args.dry_run else "write",
            "input_file": str(input_file),
            "pre_counts": pre,
            "existing_definition_audit": audit,
            "topic_mapping_count": len(mapping),
            "would_delete_definition_count": audit["definition_total"],
            "would_delete_children": {
                "problem_block": db.session.query(ProblemBlock).join(Problem, Problem.id == ProblemBlock.problem_id).filter(Problem.content_kind == PROBLEM_CONTENT_KIND_DEFINITION).count(),
                "problem_accepted_answer": db.session.query(ProblemAcceptedAnswer).join(Problem, Problem.id == ProblemAcceptedAnswer.problem_id).filter(Problem.content_kind == PROBLEM_CONTENT_KIND_DEFINITION).count(),
                "problem_source_metadata": db.session.query(ProblemSourceMetadata).join(Problem, Problem.id == ProblemSourceMetadata.problem_id).filter(Problem.content_kind == PROBLEM_CONTENT_KIND_DEFINITION).count(),
                "problem_set_links": audit["definitions_in_problem_sets"],
            },
            "curated_rows_total": len(rows),
            "curated_rows_importable": len(prepared),
            "curated_rows_skipped_by_reason": dict(skips),
            "final_expected_definition_count": len(prepared),
        }
        if args.dry_run:
            print(json.dumps(dry, ensure_ascii=False, indent=2))
            return 0

        deleted = delete_existing_definitions()
        inserted = insert_curated(prepared, input_file)
        post = db_counts()
        print(json.dumps({**dry, "write_result": {"deleted": deleted, "inserted": inserted}, "post_counts": post}, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
