from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GAME_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = Path(r"C:\Users\korol\OneDrive\Desktop\IB Physics Question System")
DEFAULT_OUTPUT_DIR = GAME_ROOT / "instance" / "definition_import_preview"
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")

SUBJECT_NAME = "IB DP Physics"
CONTENT_KIND = "definition"
ANSWER_TYPE = "text_input"
CONFIDENCE_VALUES = {"high", "medium", "low"}
COMPOUND_SEPARATORS = [" and ", " or ", "/", ",", ";"]


@dataclass
class SourceDefinition:
    source_id: str
    source_path: str
    source_term: str | None
    source_definition: str
    source_topic_code: str | None
    source_subtopic_code: str | None
    source_topic_title: str | None
    source_subtopic_title: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare IB Physics definition conversion previews only (no DB writes).")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--bank", choices=["core", "extension", "combined"], default="combined")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--topic", default="")
    parser.add_argument("--subtopic", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-vertex", action="store_true")
    parser.add_argument("--from-raw", action="store_true")
    parser.add_argument("--raw-input", type=Path)
    parser.add_argument("--max-retries", type=int, default=3)
    return parser.parse_args()


def normalize_space(value: object) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def norm_casefold(value: object) -> str:
    return normalize_space(value).casefold()


def as_list_of_str(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [normalize_space(v) for v in value if normalize_space(v)]
    scalar = normalize_space(value)
    return [scalar] if scalar else []


def is_compound_phrase(text: str) -> bool:
    t = norm_casefold(text)
    return any(sep in t for sep in COMPOUND_SEPARATORS)


def split_compound_term(text: str) -> list[str]:
    parts = re.split(r"\s+(?:and|or)\s+|/|,|;", normalize_space(text), flags=re.I)
    return [normalize_space(part) for part in parts if normalize_space(part)]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_taxonomy(source_root: Path) -> tuple[dict[str, str], dict[str, str]]:
    data = json.loads((source_root / "docs" / "ib_taxonomy.json").read_text(encoding="utf-8"))
    topic_titles: dict[str, str] = {}
    subtopic_titles: dict[str, str] = {}
    for topic in data.get("topics", []):
        topic_code = normalize_space(topic.get("topic_code", "")).upper()
        topic_titles[topic_code] = normalize_space(topic.get("topic_title", ""))
        for subtopic in topic.get("subtopics", []):
            subtopic_code = normalize_space(subtopic.get("subtopic_code", ""))
            subtopic_titles[subtopic_code] = normalize_space(subtopic.get("subtopic_title", ""))
    return topic_titles, subtopic_titles


def core_definitions_path(source_root: Path) -> Path:
    return source_root / "Analysis" / "exports" / "definitions_bank.csv"


def extension_definitions_path(source_root: Path) -> Path:
    return source_root / "data" / "definitions_extension_bank.csv"


def load_core_definitions(source_root: Path, topic_titles: dict[str, str], subtopic_titles: dict[str, str]) -> list[SourceDefinition]:
    rows = read_csv(core_definitions_path(source_root))
    counters: dict[str, int] = defaultdict(int)
    out: list[SourceDefinition] = []
    for row in rows:
        subtopic_code = normalize_space(row.get("subtopic", ""))
        topic_code = subtopic_code.split(".", 1)[0] if "." in subtopic_code else ""
        counters[subtopic_code] += 1
        out.append(
            SourceDefinition(
                source_id=f"defcore_{subtopic_code.replace('.', '')}_{counters[subtopic_code]:03d}",
                source_path=str(core_definitions_path(source_root)),
                source_term=normalize_space(row.get("item", "")) or None,
                source_definition=normalize_space(row.get("expected_statement", "")),
                source_topic_code=topic_code or None,
                source_subtopic_code=subtopic_code or None,
                source_topic_title=topic_titles.get(topic_code) or None,
                source_subtopic_title=subtopic_titles.get(subtopic_code) or None,
            )
        )
    return out


def load_extension_definitions(source_root: Path, topic_titles: dict[str, str], subtopic_titles: dict[str, str]) -> list[SourceDefinition]:
    rows = read_csv(extension_definitions_path(source_root))
    out: list[SourceDefinition] = []
    for row in rows:
        if normalize_space(row.get("active", "")).casefold() != "true":
            continue
        topic_code = normalize_space(row.get("topic_code", "")).upper()
        subtopic_code = normalize_space(row.get("subtopic_code", ""))
        out.append(
            SourceDefinition(
                source_id=normalize_space(row.get("definition_id", "")),
                source_path=str(extension_definitions_path(source_root)),
                source_term=normalize_space(row.get("term", "")) or None,
                source_definition=normalize_space(row.get("definition", "")),
                source_topic_code=topic_code or None,
                source_subtopic_code=subtopic_code or None,
                source_topic_title=topic_titles.get(topic_code) or None,
                source_subtopic_title=normalize_space(row.get("subtopic_label", "")) or subtopic_titles.get(subtopic_code) or None,
            )
        )
    return out


def discover_sources(source_root: Path) -> dict[str, Any]:
    topic_titles, subtopic_titles = load_taxonomy(source_root)
    core = load_core_definitions(source_root, topic_titles, subtopic_titles)
    ext = load_extension_definitions(source_root, topic_titles, subtopic_titles)
    return {"core": core, "extension": ext}


def choose_bank(discovery: dict[str, Any], bank: str) -> list[SourceDefinition]:
    if bank == "core":
        return list(discovery["core"])
    if bank == "extension":
        return list(discovery["extension"])
    return list(discovery["core"]) + list(discovery["extension"])


def apply_filters(items: list[SourceDefinition], topic: str, subtopic: str, limit: int) -> list[SourceDefinition]:
    out = list(items)
    if topic:
        out = [i for i in out if (i.source_topic_code or "").upper() == normalize_space(topic).upper()]
    if subtopic:
        out = [i for i in out if (i.source_subtopic_code or "") == normalize_space(subtopic)]
    if limit > 0:
        out = out[:limit]
    return out


def extract_json_from_text(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def build_client() -> Any:
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() != "true":
        raise SystemExit("Set GOOGLE_GENAI_USE_VERTEXAI=true before Vertex calls.")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION")
    if not project or not location:
        raise SystemExit("Set GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION before Vertex calls.")
    from google import genai
    return genai.Client(vertexai=True, project=project, location=location)


def model_prompt(source: SourceDefinition) -> str:
    payload = {
        "source_id": source.source_id,
        "source_path": source.source_path,
        "source_term": source.source_term,
        "source_definition": source.source_definition,
        "source_topic_code": source.source_topic_code,
        "source_subtopic_code": source.source_subtopic_code,
        "source_topic_title": source.source_topic_title,
        "source_subtopic_title": source.source_subtopic_title,
    }
    return (
        "You are converting textbook-style IB Physics definitions into atomic short-answer tasks.\n"
        "Each generated task must have exactly one expected answer.\n"
        "If the source contains a compound term such as speed and velocity or distance and displacement, "
        "split it into separate tasks only if the definition text clearly supports separate prompts.\n"
        "Never set expected_answer to a phrase containing multiple different terms joined by and/or/slash/comma/semicolon.\n"
        "If you cannot create one clear prompt with one clear correct response, return no atomic task and mark the source for review.\n"
        "The student sees the definition and must type the term/quantity.\n"
        "The prompt must make the expected answer unambiguous.\n"
        "Confidence calibration rules:\n"
        '- Set confidence="high" when source term is explicit, expected_answer is one clear term, prompt closely matches source definition, and there are no warnings/conflicts.\n'
        '- Set confidence="medium" when a compound source row is cleanly split into separate atomic tasks or when minor wording rewrite was needed but answer remains clear.\n'
        '- Set confidence="low" only when term is inferred, source conflict/vagueness exists, prompt may imply multiple answers, or manual review is needed.\n'
        "Do not mark all valid tasks low. Use low only for genuinely risky tasks.\n"
        "Return strict JSON only with fields source_* + atomic_tasks[] + source_warnings.\n\n"
        f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def fallback_no_vertex(source: SourceDefinition) -> dict[str, Any]:
    term = normalize_space(source.source_term or "")
    atomic_tasks = []
    source_warnings: list[str] = []
    if not term:
        source_warnings.append("Missing source term; no atomic task created.")
    elif is_compound_phrase(term):
        source_warnings.append("Compound source term cannot be safely converted in fallback mode; no atomic tasks created.")
        parts = split_compound_term(term)
        if len(parts) > 1:
            source_warnings.append(f"Candidate split terms: {', '.join(parts)}")
    else:
        atomic_tasks.append(
            {
                "atomic_id": f"{source.source_id}__a1",
                "game_subject": SUBJECT_NAME,
                "game_topic_code": source.source_subtopic_code or source.source_topic_code or "",
                "game_topic_name": source.source_subtopic_title or source.source_topic_title or "",
                "content_kind": CONTENT_KIND,
                "answer_type": ANSWER_TYPE,
                "title": f"Definition: {term}",
                "prompt": f'Which physical quantity or term is defined as: "{source.source_definition}"?',
                "expected_answer": term,
                "accepted_answers": [term],
                "answer_symbols": [],
                "confidence": "high",
                "needs_review": False,
                "warnings": [],
            }
        )
    return {
        "source_id": source.source_id,
        "source_path": source.source_path,
        "source_topic_code": source.source_topic_code,
        "source_subtopic_code": source.source_subtopic_code,
        "source_topic_title": source.source_topic_title,
        "source_subtopic_title": source.source_subtopic_title,
        "source_term": source.source_term,
        "source_definition": source.source_definition,
        "atomic_tasks": atomic_tasks,
        "source_warnings": source_warnings,
    }


def call_vertex_once(client: Any, model: str, prompt: str) -> str:
    from google.genai import types
    response = client.models.generate_content(
        model=model,
        contents=[prompt],
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
    )
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    parts: list[str] = []
    for c in getattr(response, "candidates", None) or []:
        for p in getattr(getattr(c, "content", None), "parts", None) or []:
            ptxt = getattr(p, "text", None)
            if isinstance(ptxt, str) and ptxt.strip():
                parts.append(ptxt)
    return "\n".join(parts)


def convert_one(client: Any | None, model: str, source: SourceDefinition, no_vertex: bool, max_retries: int) -> dict[str, Any]:
    if no_vertex:
        payload = fallback_no_vertex(source)
        return {
            "source_id": source.source_id,
            "source_path": source.source_path,
            "raw_model_response_text": json.dumps(payload, ensure_ascii=False),
            "parsed_json": payload,
            "api_or_parsing_error": "",
            "model_name": "no_vertex_fallback",
            "timestamp": int(time.time()),
        }
    prompt = model_prompt(source)
    raw_text = ""
    parsed = None
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            raw_text = call_vertex_once(client, model, prompt)
            parsed = extract_json_from_text(raw_text)
            last_error = ""
            break
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < max_retries:
                time.sleep(min(2**attempt, 10))
    return {
        "source_id": source.source_id,
        "source_path": source.source_path,
        "raw_model_response_text": raw_text,
        "parsed_json": parsed,
        "api_or_parsing_error": last_error,
        "model_name": model,
        "timestamp": int(time.time()),
    }


def normalize_source_payload(parsed: dict[str, Any], source: SourceDefinition) -> dict[str, Any]:
    data = dict(parsed or {})
    data["source_id"] = normalize_space(data.get("source_id", "")) or source.source_id
    data["source_path"] = normalize_space(data.get("source_path", "")) or source.source_path
    data["source_term"] = normalize_space(data.get("source_term", "")) or source.source_term
    data["source_definition"] = normalize_space(data.get("source_definition", "")) or source.source_definition
    data["source_topic_code"] = normalize_space(data.get("source_topic_code", "")) or source.source_topic_code
    data["source_subtopic_code"] = normalize_space(data.get("source_subtopic_code", "")) or source.source_subtopic_code
    data["source_topic_title"] = normalize_space(data.get("source_topic_title", "")) or source.source_topic_title
    data["source_subtopic_title"] = normalize_space(data.get("source_subtopic_title", "")) or source.source_subtopic_title
    data["atomic_tasks"] = data.get("atomic_tasks") if isinstance(data.get("atomic_tasks"), list) else []
    data["source_warnings"] = as_list_of_str(data.get("source_warnings"))
    return data


def normalize_atomic_task(task: dict[str, Any], payload: dict[str, Any], idx: int) -> dict[str, Any]:
    t = dict(task or {})
    t["atomic_id"] = normalize_space(t.get("atomic_id", "")) or f"{payload['source_id']}__a{idx}"
    t["game_subject"] = SUBJECT_NAME
    t["game_topic_code"] = normalize_space(t.get("game_topic_code", "")) or payload.get("source_subtopic_code") or payload.get("source_topic_code") or ""
    t["game_topic_name"] = normalize_space(t.get("game_topic_name", "")) or payload.get("source_subtopic_title") or payload.get("source_topic_title") or ""
    t["content_kind"] = CONTENT_KIND
    t["answer_type"] = ANSWER_TYPE
    t["title"] = normalize_space(t.get("title", ""))
    t["prompt"] = normalize_space(t.get("prompt", ""))
    t["expected_answer"] = normalize_space(t.get("expected_answer", ""))
    t["accepted_answers"] = as_list_of_str(t.get("accepted_answers"))
    if t["expected_answer"] and not t["accepted_answers"] and not is_compound_phrase(t["expected_answer"]):
        t["accepted_answers"] = [t["expected_answer"]]
    t["answer_symbols"] = as_list_of_str(t.get("answer_symbols"))
    t["model_confidence"] = norm_casefold(t.get("model_confidence", t.get("confidence", "low")))
    t["confidence"] = t["model_confidence"]
    t["needs_review"] = bool(t.get("needs_review"))
    t["warnings"] = as_list_of_str(t.get("warnings"))
    return t


def validate_atomic_task(task: dict[str, Any], source_definition_text: str) -> list[str]:
    issues: list[str] = []
    expected = normalize_space(task.get("expected_answer", ""))
    prompt = normalize_space(task.get("prompt", ""))
    confidence = norm_casefold(task.get("confidence", ""))
    accepted = as_list_of_str(task.get("accepted_answers"))
    if not expected:
        issues.append("expected_answer is missing.")
    if expected and is_compound_phrase(expected):
        issues.append(f'expected_answer is compound and invalid: "{expected}"')
    if not prompt:
        issues.append("prompt is missing.")
    if prompt:
        multi_answer_patterns = [
            r"\bwhich (?:two|three|multiple)\b",
            r"\b(?:terms|quantities|answers?)\s+(?:are|were)\b",
            r"\banswers?\b",
            r"\blist\b",
            r"\bname\s+two\b",
        ]
        if any(re.search(pattern, prompt, flags=re.I) for pattern in multi_answer_patterns):
            issues.append("prompt may imply multiple expected answers.")
    if norm_casefold(task.get("content_kind", "")) != CONTENT_KIND:
        issues.append('content_kind must be "definition".')
    if norm_casefold(task.get("answer_type", "")) != ANSWER_TYPE:
        issues.append('answer_type must be "text_input".')
    if confidence not in CONFIDENCE_VALUES:
        issues.append("confidence must be high|medium|low.")
    if confidence in {"high", "medium"} and not accepted:
        issues.append("accepted_answers must be non-empty for high/medium confidence.")
    definition_words = len(normalize_space(source_definition_text).split())
    for ans in accepted:
        if is_compound_phrase(ans):
            issues.append(f'accepted_answers contains compound value: "{ans}"')
        if len(ans.split()) >= max(12, definition_words):
            issues.append(f'accepted answer appears too long: "{ans}"')
    return issues


def flatten_atomic_tasks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for idx, task in enumerate(payload.get("atomic_tasks", []), start=1):
        t = normalize_atomic_task(task, payload, idx)
        out.append(
            {
                "source_id": payload.get("source_id", ""),
                "source_path": payload.get("source_path", ""),
                "source_term": payload.get("source_term", ""),
                "source_definition": payload.get("source_definition", ""),
                "source_topic_code": payload.get("source_topic_code", ""),
                "source_subtopic_code": payload.get("source_subtopic_code", ""),
                "source_topic_title": payload.get("source_topic_title", ""),
                "source_subtopic_title": payload.get("source_subtopic_title", ""),
                "source_warnings": as_list_of_str(payload.get("source_warnings")),
                **t,
            }
        )
    return out


def calibrate_atomic_task_confidence(task: dict[str, Any], source_term: str, source_warnings: list[str], validation_issues: list[str], source_has_compound_split: bool) -> dict[str, Any]:
    t = dict(task)
    warnings = as_list_of_str(t.get("warnings")) + as_list_of_str(source_warnings)
    has_prompt_ambiguity = any("prompt may imply multiple expected answers." in w for w in warnings)
    has_source_conflict = any("conflict" in norm_casefold(w) for w in warnings)
    has_validation_failure = bool(validation_issues)
    expected = normalize_space(t.get("expected_answer", ""))
    accepted = as_list_of_str(t.get("accepted_answers"))
    explicit_source_term = normalize_space(source_term)
    if expected and not accepted:
        accepted = [expected]
        t["accepted_answers"] = accepted

    if has_validation_failure:
        t["confidence"] = "low"
        t["needs_review"] = True
    elif has_prompt_ambiguity or has_source_conflict:
        t["confidence"] = "low"
        t["needs_review"] = True
    elif source_has_compound_split:
        t["confidence"] = "medium"
    elif explicit_source_term and norm_casefold(explicit_source_term) == norm_casefold(expected) and not warnings:
        t["confidence"] = "high"
    elif not warnings and expected:
        t["confidence"] = "medium"
    else:
        t["confidence"] = "low"
        t["needs_review"] = True
    return t


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_review_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "source_id", "atomic_id", "source_topic_code", "source_subtopic_code", "source_term", "source_definition",
        "prompt", "expected_answer", "accepted_answers", "model_confidence", "confidence", "needs_review", "warnings", "source_warnings",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    "source_id": r.get("source_id", ""),
                    "atomic_id": r.get("atomic_id", ""),
                    "source_topic_code": r.get("source_topic_code", ""),
                    "source_subtopic_code": r.get("source_subtopic_code", ""),
                    "source_term": r.get("source_term", ""),
                    "source_definition": r.get("source_definition", ""),
                    "prompt": r.get("prompt", ""),
                    "expected_answer": r.get("expected_answer", ""),
                    "accepted_answers": " | ".join(as_list_of_str(r.get("accepted_answers"))),
                    "model_confidence": r.get("model_confidence", ""),
                    "confidence": r.get("confidence", ""),
                    "needs_review": r.get("needs_review", ""),
                    "warnings": " | ".join(as_list_of_str(r.get("warnings"))),
                    "source_warnings": " | ".join(as_list_of_str(r.get("source_warnings"))),
                }
            )


def write_audit(path: Path, source_count: int, traces: list[dict[str, Any]], source_payloads: list[dict[str, Any]], flattened: list[dict[str, Any]], validation: dict[str, list[str]], compound_source_term_count: int, compound_expected_invalid_count: int) -> None:
    conf = Counter(norm_casefold(r.get("confidence", "")) for r in flattened)
    model_conf = Counter(norm_casefold(r.get("model_confidence", "")) for r in flattened)
    task_counts = [len(p.get("atomic_tasks", [])) for p in source_payloads]
    skipped = []
    split = []
    for p in source_payloads:
        term = normalize_space(p.get("source_term", ""))
        cnt = len(p.get("atomic_tasks", []))
        if term and is_compound_phrase(term) and cnt == 0 and len(skipped) < 8:
            skipped.append(f"{p.get('source_id')}: {term}")
        if term and is_compound_phrase(term) and cnt > 1 and len(split) < 8:
            split.append(f"{p.get('source_id')}: {term}")
    lines = [
        "# Definitions Conversion Audit",
        "",
        f"- source rows read: {source_count}",
        f"- atomic tasks produced: {len(flattened)}",
        f"- sources producing 0 tasks: {sum(1 for c in task_counts if c == 0)}",
        f"- sources producing 1 task: {sum(1 for c in task_counts if c == 1)}",
        f"- sources producing multiple tasks: {sum(1 for c in task_counts if c > 1)}",
        f"- failed parse count: {sum(1 for t in traces if t.get('api_or_parsing_error'))}",
        f"- compound source term count: {compound_source_term_count}",
        f"- compound expected_answer invalid count: {compound_expected_invalid_count}",
        f"- needs_review count: {sum(1 for r in flattened if r.get('needs_review'))}",
        f"- low-confidence count: {conf.get('low', 0)}",
        f"- confidence high: {conf.get('high', 0)}",
        f"- confidence medium: {conf.get('medium', 0)}",
        f"- confidence low: {conf.get('low', 0)}",
        f"- model_confidence high: {model_conf.get('high', 0)}",
        f"- model_confidence medium: {model_conf.get('medium', 0)}",
        f"- model_confidence low: {model_conf.get('low', 0)}",
        "",
        "## Validation Failures",
        "",
    ]
    lines.extend([f"- {k}: {'; '.join(v)}" for k, v in sorted(validation.items())] or ["- none"])
    lines.extend(["", "## Examples Of Skipped Compound Rows", ""])
    lines.extend([f"- {x}" for x in skipped] or ["- none"])
    lines.extend(["", "## Examples Of Split Compound Rows", ""])
    lines.extend([f"- {x}" for x in split] or ["- none"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize_discovery(discovery: dict[str, Any], source_root: Path) -> dict[str, Any]:
    core = discovery["core"]
    ext = discovery["extension"]
    return {
        "core_path": str(core_definitions_path(source_root)),
        "extension_path": str(extension_definitions_path(source_root)),
        "core_count": len(core),
        "extension_count": len(ext),
        "combined_count": len(core) + len(ext),
    }


def run_conversion(args: argparse.Namespace, selected: list[SourceDefinition]) -> None:
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "definitions_vertex_raw.jsonl"
    converted_jsonl_path = output_dir / "definitions_converted.jsonl"
    converted_json_path = output_dir / "definitions_converted.json"
    review_csv_path = output_dir / "definitions_review.csv"
    audit_path = output_dir / "definitions_conversion_audit.md"

    if args.from_raw:
        traces = read_jsonl(args.raw_input or raw_path)
    else:
        client = None if args.no_vertex else build_client()
        traces = []
        for idx, source in enumerate(selected, start=1):
            print(f"[{idx}/{len(selected)}] converting {source.source_id}", flush=True)
            traces.append(convert_one(client, args.model, source, args.no_vertex, args.max_retries))
        write_jsonl(raw_path, traces)

    source_by_id = {s.source_id: s for s in selected}
    source_payloads = []
    flattened = []
    validation_failures: dict[str, list[str]] = {}
    compound_expected_invalid_count = 0
    for trace in traces:
        source_id = normalize_space(trace.get("source_id", ""))
        source = source_by_id.get(source_id)
        if not source:
            continue
        parsed = trace.get("parsed_json")
        payload = normalize_source_payload(parsed if isinstance(parsed, dict) else {}, source)
        if not isinstance(parsed, dict):
            payload["source_warnings"] = [f"parse failure: {trace.get('api_or_parsing_error', 'unknown')}"]
        normalized_tasks = []
        source_term = normalize_space(payload.get("source_term", ""))
        source_has_compound_split = is_compound_phrase(source_term) and len(payload.get("atomic_tasks", [])) > 1
        for idx, task in enumerate(payload.get("atomic_tasks", []), start=1):
            t = normalize_atomic_task(task, payload, idx)
            issues = validate_atomic_task(t, payload.get("source_definition", ""))
            if any("expected_answer is compound" in issue for issue in issues):
                compound_expected_invalid_count += 1
            if issues:
                t["needs_review"] = True
                t["warnings"] = as_list_of_str(t.get("warnings")) + issues
                validation_failures[f"{payload['source_id']}::{t['atomic_id']}"] = issues
            t = calibrate_atomic_task_confidence(
                t,
                source_term=source_term,
                source_warnings=as_list_of_str(payload.get("source_warnings")),
                validation_issues=issues,
                source_has_compound_split=source_has_compound_split,
            )
            normalized_tasks.append(t)
        payload["atomic_tasks"] = normalized_tasks
        source_payloads.append(payload)
        flattened.extend(flatten_atomic_tasks(payload))

    write_jsonl(converted_jsonl_path, flattened)
    converted_json_path.write_text(json.dumps(flattened, ensure_ascii=False, indent=2), encoding="utf-8")
    write_review_csv(review_csv_path, flattened)
    write_audit(
        audit_path,
        len(selected),
        traces,
        source_payloads,
        flattened,
        validation_failures,
        sum(1 for s in selected if is_compound_phrase(normalize_space(s.source_term or ""))),
        compound_expected_invalid_count,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "mode": "from_raw" if args.from_raw else "convert",
                "selected_source_count": len(selected),
                "raw_output": str(raw_path),
                "converted_jsonl": str(converted_jsonl_path),
                "converted_json": str(converted_json_path),
                "review_csv": str(review_csv_path),
                "audit_md": str(audit_path),
                "atomic_tasks_count": len(flattened),
                "failed_parse_count": sum(1 for t in traces if t.get("api_or_parsing_error")),
                "validation_failed_count": len(validation_failures),
                "dry_run": bool(args.dry_run),
            },
            indent=2,
        )
    )


def select_for_run(args: argparse.Namespace, discovered_items: list[SourceDefinition]) -> list[SourceDefinition]:
    selected = apply_filters(discovered_items, args.topic, args.subtopic, args.limit)
    if args.sample > 0:
        selected = selected[: args.sample]
    elif args.all:
        selected = selected
    elif not args.discover and not args.from_raw:
        raise SystemExit("Select either --sample N or --all for conversion runs.")
    return selected


def main() -> None:
    args = parse_args()
    source_root = args.source_root.resolve()
    discovery = discover_sources(source_root)
    summary = summarize_discovery(discovery, source_root)
    bank_items = choose_bank(discovery, args.bank)
    selected = select_for_run(args, bank_items)
    if args.discover:
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "discover",
                    "source_root": str(source_root),
                    "bank": args.bank,
                    "candidate_count_for_bank": len(bank_items),
                    "selected_count_after_filters": len(selected),
                    **summary,
                },
                indent=2,
            )
        )
        return
    run_conversion(args, selected)


if __name__ == "__main__":
    main()
