import argparse
import html
import json
import random
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.extensions import db
from app.models.problems import (
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    PROBLEM_BLOCK_TYPE_IMAGE,
    PROBLEM_BLOCK_TYPE_RICH_TEXT,
    Problem,
    ProblemBlock,
    ProblemChoiceOption,
    ProblemSet,
    ProblemSourceMetadata,
    Topic,
)


SOURCE_SYSTEM_IB_PHYSICS = 'ib_physics_question_system'
DEFAULT_SOURCE_ROOT = r'C:\Users\korol\OneDrive\Desktop\IB Physics Question System'
DEFAULT_QUESTION_BANK = r'data\complete_questionbank\questions.json'
IB_PHYSICS_IMAGE_ROOT = Path('data') / 'complete_questionbank' / 'images'
MCQ_LABELS = ('A', 'B', 'C', 'D')


class ImportValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ImportFilters:
    subtopics: tuple[str, ...]
    count: int
    per_subtopic_count: int | None = None
    difficulty: int | None = None
    difficulty_min: int | None = None
    difficulty_max: int | None = None
    level: str | None = None
    exclude_imported: bool = True
    seed: int | None = None
    require_image: bool = False
    no_image: bool = False
    set_name: str | None = None
    usable_in_classic: bool = True
    usable_in_boss_rush: bool = True
    usable_as_recovery: bool = False
    usable_in_team: bool = False


def load_source_bank(source_root: str | Path, question_bank: str | Path = DEFAULT_QUESTION_BANK) -> list[dict]:
    bank_path = resolve_question_bank_path(source_root, question_bank)
    payload = json.loads(bank_path.read_text(encoding='utf-8'))
    questions = payload.get('questions') if isinstance(payload, dict) else payload
    if not isinstance(questions, list):
        raise ImportValidationError(f'Question bank has no questions list: {bank_path}')
    return questions


def resolve_question_bank_path(source_root: str | Path, question_bank: str | Path) -> Path:
    candidate = Path(question_bank)
    if not candidate.is_absolute():
        candidate = Path(source_root) / candidate
    return candidate.resolve()


def source_image_path(source_root: str | Path, image_ref: str) -> Path:
    return (Path(source_root) / IB_PHYSICS_IMAGE_ROOT / image_ref).resolve()


def is_canonical_mcq(question: dict) -> bool:
    return question.get('type') == 'mcq' and question.get('paper') == 'Paper 1A'


def canonical_id_for(question: dict) -> str:
    canonical_id = (question.get('canonical_id') or '').strip()
    if canonical_id:
        return canonical_id
    fallback = (question.get('id') or question.get('source_id') or '').strip()
    if fallback:
        return fallback
    raise ImportValidationError('Source question is missing canonical_id, id, and source_id.')


def question_subtopics(question: dict) -> set[str]:
    values = set()
    for raw in question.get('subtopics') or []:
        if raw:
            values.add(str(raw).strip())
    primary = (question.get('primary_subtopic') or '').strip()
    if primary:
        values.add(primary)
    return {value for value in values if value}


def matched_subtopic(question: dict, requested_subtopics: tuple[str, ...], preferred_subtopic: str | None = None) -> str | None:
    available = question_subtopics(question)
    if preferred_subtopic and preferred_subtopic in available:
        return preferred_subtopic
    for subtopic in requested_subtopics:
        if subtopic in available:
            return subtopic
    return next(iter(sorted(available)), None)


def subtopic_title(question: dict, subtopic: str | None) -> str:
    if not subtopic:
        return ''
    titles = question.get('subtopic_titles') or {}
    return (titles.get(subtopic) or '').strip()


def topic_name_for(question: dict, requested_subtopics: tuple[str, ...], preferred_subtopic: str | None = None) -> str:
    subtopic = matched_subtopic(question, requested_subtopics, preferred_subtopic)
    if not subtopic:
        return 'IB Physics'
    title = subtopic_title(question, subtopic)
    if title:
        return f'IB Physics {subtopic} - {title}'
    return f'IB Physics {subtopic}'


def title_for(question: dict, requested_subtopics: tuple[str, ...], preferred_subtopic: str | None = None) -> str:
    source_id = (question.get('id') or question.get('source_id') or canonical_id_for(question)).strip()
    subtopic = matched_subtopic(question, requested_subtopics, preferred_subtopic)
    if subtopic:
        return f'{subtopic} MCQ - {source_id}'
    return f'IB Physics MCQ - {source_id}'


def normalize_question_text(question: dict) -> str:
    raw = question.get('question_text')
    if not raw:
        raw = html_to_text(question.get('question_html') or '')
    text = str(raw or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    lines = [line for line in text.split('\n') if line.strip() != '[image]']
    return normalize_embedded_mcq_text('\n'.join(lines)).strip()


def normalize_embedded_mcq_text(text: str) -> str:
    normalized = text
    normalized = re.sub(r'(?<!\n)\s+(I{1,3})\.\s+', r'\n\1. ', normalized)
    normalized = re.sub(r'(?<=[^\n])\s+(Which\b)', r'\n\n\1', normalized)
    for option_text in (
        'I and II only',
        'I and III only',
        'II and III only',
        'I, II and III',
    ):
        normalized = re.sub(
            rf'(?<!\n)\s+({re.escape(option_text)})(?=\s|$)',
            r'\n\1',
            normalized,
        )
    return re.sub(r'\n{3,}', '\n\n', normalized)


def html_to_text(source: str) -> str:
    text = re.sub(r'<\s*br\s*/?\s*>', '\n', source, flags=re.IGNORECASE)
    text = re.sub(r'</\s*(p|div|li|tr|table)\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text)


def source_answer_letter(question: dict) -> str:
    answer = str(question.get('answer') or question.get('markscheme_text') or '').strip().upper()
    match = re.search(r'\b([ABCD])\b', answer)
    if not match:
        raise ImportValidationError(f'Question {question.get("id") or canonical_id_for(question)} has no A-D answer.')
    return match.group(1)


def normalize_options(question: dict) -> tuple[list[dict], bool]:
    source_options = question.get('options') or []
    by_label = {}
    for option in source_options:
        label = str(option.get('label') or '').strip().upper()
        if label in MCQ_LABELS:
            text = str(option.get('text') or '').strip()
            if not text:
                text = html_to_text(option.get('html') or '').strip()
            by_label[label] = text

    if len(by_label) == 4:
        return [
            {'label': label, 'text': f'{label}. {by_label[label]}', 'source_text': by_label[label]}
            for label in MCQ_LABELS
        ], True

    return [
        {'label': label, 'text': label, 'source_text': ''}
        for label in MCQ_LABELS
    ], False


def extract_embedded_choice_options(text: str) -> tuple[str, list[dict]]:
    source = (text or '').strip()
    if not source:
        return source, []

    labelled = extract_labelled_choice_options(source)
    if labelled[1]:
        return labelled

    roman = extract_roman_choice_options(source)
    if roman[1]:
        return roman

    math_choices = extract_trailing_math_choice_options(source)
    if math_choices[1]:
        return math_choices

    numeric_choices = extract_trailing_numeric_choice_options(source)
    if numeric_choices[1]:
        return numeric_choices

    sentence_choices = extract_trailing_sentence_choice_options(source)
    if sentence_choices[1]:
        return sentence_choices

    return source, []


def _make_choice_options(option_texts: list[str]) -> list[dict]:
    return [
        {'label': label, 'text': f'{label}. {text.strip()}', 'source_text': text.strip()}
        for label, text in zip(MCQ_LABELS, option_texts)
    ]


def extract_labelled_choice_options(text: str) -> tuple[str, list[dict]]:
    matches = list(re.finditer(r'(?:(?<=^)|(?<=\n)|(?<=\s))([ABCD])\.\s+', text))
    labels = [match.group(1) for match in matches]
    for start_index in range(0, len(matches) - 3):
        if labels[start_index:start_index + 4] != list(MCQ_LABELS):
            continue
        selected = matches[start_index:start_index + 4]
        if selected[0].start() < max(40, len(text) // 3):
            continue
        body = text[:selected[0].start()].strip()
        option_texts = []
        for index, match in enumerate(selected):
            start = match.end()
            end = selected[index + 1].start() if index < 3 else len(text)
            option_texts.append(text[start:end].strip())
        if body and all(option_texts):
            return body, _make_choice_options(option_texts)
    return text, []


def extract_roman_choice_options(text: str) -> tuple[str, list[dict]]:
    option_texts = ['I and II only', 'I and III only', 'II and III only', 'I, II and III']
    positions = []
    for option_text in option_texts:
        match = re.search(rf'(?<!\S){re.escape(option_text)}(?!\S)', text)
        if not match:
            return text, []
        positions.append(match.start())
    if positions != sorted(positions) or positions[0] < max(40, len(text) // 3):
        return text, []
    tail = text[positions[0]:].strip()
    compact_tail = re.sub(r'\s+', ' ', tail)
    if compact_tail != ' '.join(option_texts):
        return text, []
    return text[:positions[0]].strip(), _make_choice_options(option_texts)


def extract_trailing_math_choice_options(text: str) -> tuple[str, list[dict]]:
    stem_end = trailing_choice_stem_end(text)
    if stem_end < max(10, len(text) // 5):
        return text, []
    stem = text[:stem_end + 1].strip()
    tail = text[stem_end + 1:].strip()
    if not tail:
        return text, []

    math_spans = list(re.finditer(r'\$(?:\\.|[^$])+\$', tail))
    if len(math_spans) != 4:
        return text, []

    option_texts = []
    cursor = 0
    for index, match in enumerate(math_spans):
        prefix = tail[cursor:match.start()].strip()
        if prefix:
            return text, []
        next_start = math_spans[index + 1].start() if index < 3 else len(tail)
        raw_option = tail[match.start():next_start].strip()
        option_texts.append(raw_option)
        cursor = next_start

    if all(option_texts):
        return stem, _make_choice_options(option_texts)
    return text, []


def trailing_choice_stem_end(text: str) -> int:
    question_index = text.rfind('?')
    if question_index >= 0:
        return question_index
    colon_matches = list(re.finditer(r'(?<!\\):', text))
    return colon_matches[-1].start() if colon_matches else -1


def extract_trailing_numeric_choice_options(text: str) -> tuple[str, list[dict]]:
    stem_end = trailing_choice_stem_end(text)
    if stem_end < max(10, len(text) // 5):
        return text, []
    stem = text[:stem_end + 1].strip()
    tail = text[stem_end + 1:].strip()
    if not tail:
        return text, []

    patterns = (
        r'-?\d+(?:\.\d+)?\s*K',
        r'\d+(?:\.\d+)?\s*m\s*s\s*\$\^\{-1\}\$',
    )
    for pattern in patterns:
        matches = list(re.finditer(pattern, tail))
        if len(matches) != 4:
            continue
        rebuilt = ' '.join(match.group(0) for match in matches)
        if re.sub(r'\s+', ' ', tail).strip() == rebuilt:
            return stem, _make_choice_options([match.group(0) for match in matches])
    return text, []


def extract_trailing_sentence_choice_options(text: str) -> tuple[str, list[dict]]:
    stem_end = trailing_choice_stem_end(text)
    if stem_end < max(10, len(text) // 5):
        return text, []
    stem = text[:stem_end + 1].strip()
    tail = text[stem_end + 1:].strip()
    if not tail or '$' in tail:
        return text, []

    if tail.endswith('.') and tail.count('.') == 4:
        sentence_parts = [part.strip() + '.' for part in tail[:-1].split('.') if part.strip()]
        if len(sentence_parts) == 4:
            return stem, _make_choice_options(sentence_parts)

    starts = list(re.finditer(r'(?<!\S)(?:The|It)\s+', tail))
    if len(starts) == 4:
        option_texts = []
        for index, match in enumerate(starts):
            end = starts[index + 1].start() if index < 3 else len(tail)
            option_texts.append(tail[match.start():end].strip())
        if all(option_texts):
            return stem, _make_choice_options(option_texts)
    return text, []


def question_level_matches(question: dict, level: str | None) -> bool:
    if not level:
        return True
    normalized = level.strip().upper()
    source_level = str(question.get('level') or '').strip().upper()
    available_for = {str(item).strip().upper() for item in question.get('available_for') or []}
    return source_level == normalized or normalized in available_for


def question_difficulty_matches(question: dict, filters: ImportFilters) -> bool:
    difficulty = question.get('difficulty')
    if filters.difficulty is not None:
        return difficulty == filters.difficulty
    if filters.difficulty_min is not None and (difficulty is None or difficulty < filters.difficulty_min):
        return False
    if filters.difficulty_max is not None and (difficulty is None or difficulty > filters.difficulty_max):
        return False
    return True


def source_metadata_values(question: dict) -> dict:
    return {
        'id': question.get('id'),
        'paper': question.get('paper'),
        'type': question.get('type'),
        'source_id': question.get('source_id'),
        'subtopics': question.get('subtopics') or [],
        'primary_subtopic': question.get('primary_subtopic'),
        'subtopic_titles': question.get('subtopic_titles') or {},
        'difficulty': question.get('difficulty'),
        'level': question.get('level'),
        'available_for': question.get('available_for') or [],
    }


def existing_imported_canonical_ids() -> set[str]:
    rows = ProblemSourceMetadata.query.filter_by(source_system=SOURCE_SYSTEM_IB_PHYSICS).all()
    return {row.canonical_id for row in rows}


def build_import_plan(
    *,
    source_root: str | Path,
    question_bank: str | Path,
    filters: ImportFilters,
    static_root: str | Path,
) -> dict:
    if not filters.subtopics:
        raise ImportValidationError('At least one --subtopic is required.')
    if filters.count < 1:
        raise ImportValidationError('--count must be at least 1.')
    if filters.per_subtopic_count is not None and filters.per_subtopic_count < 1:
        raise ImportValidationError('--per-subtopic-count must be at least 1.')
    if filters.per_subtopic_count is not None and filters.count != filters.per_subtopic_count * len(filters.subtopics):
        raise ImportValidationError('--count must equal --per-subtopic-count multiplied by the number of subtopics.')
    if filters.require_image and filters.no_image:
        raise ImportValidationError('--require-image and --no-image cannot both be used.')

    source_root = Path(source_root).resolve()
    question_bank_path = resolve_question_bank_path(source_root, question_bank)
    static_root = Path(static_root).resolve()
    questions = load_source_bank(source_root, question_bank_path)
    source_mcqs = [q for q in questions if is_canonical_mcq(q)]
    imported_ids = existing_imported_canonical_ids() if filters.exclude_imported else set()

    matching_before_dedupe = []
    duplicate_in_selection_exclusions = []
    seen = set()
    for question in source_mcqs:
        canonical_id = canonical_id_for(question)
        if not (question_subtopics(question) & set(filters.subtopics)):
            continue
        if not question_difficulty_matches(question, filters):
            continue
        if not question_level_matches(question, filters.level):
            continue
        if filters.require_image and not (question.get('images') or []):
            continue
        if filters.no_image and (question.get('images') or []):
            continue

        matching_before_dedupe.append(question)
        if canonical_id in seen:
            duplicate_in_selection_exclusions.append(_skip_row(question, 'duplicate canonical_id in source match set'))
            continue
        seen.add(canonical_id)

    matching_after_source_dedupe = []
    duplicate_import_exclusions = []
    for question in matching_before_dedupe:
        canonical_id = canonical_id_for(question)
        if canonical_id in imported_ids:
            duplicate_import_exclusions.append(_skip_row(question, 'already imported canonical_id'))
            continue
        if canonical_id in {canonical_id_for(q) for q in matching_after_source_dedupe}:
            continue
        matching_after_source_dedupe.append(question)

    rng = random.Random(filters.seed)
    pool = select_pool(matching_after_source_dedupe, filters, rng)

    if len(pool) < filters.count:
        raise ImportValidationError(
            f'Insufficient questions after filters and duplicate exclusion: requested {filters.count}, available {len(pool)}.'
        )

    selected = pool[:filters.count]
    set_slug = slugify(filters.set_name or default_set_name(filters))
    selected_rows = [
        build_selected_question_row(
            question=question,
            assigned_subtopic=assigned_subtopic,
            source_root=source_root,
            question_bank_path=question_bank_path,
            static_root=static_root,
            set_slug=set_slug,
            requested_subtopics=filters.subtopics,
        )
        for question, assigned_subtopic in selected
    ]

    skipped = []
    for row in selected_rows:
        if not row['text']:
            skipped.append({'canonical_id': row['canonical_id'], 'reason': 'missing question text'})
        for image in row['images']:
            if not image['exists']:
                skipped.append({'canonical_id': row['canonical_id'], 'reason': f'missing image: {image["source_ref"]}'})
    if skipped:
        detail = '; '.join(f'{item["canonical_id"]}: {item["reason"]}' for item in skipped[:5])
        raise ImportValidationError(f'Selected questions failed validation: {detail}')

    return {
        'filters': {
            'subtopics': list(filters.subtopics),
            'count': filters.count,
            'per_subtopic_count': filters.per_subtopic_count,
            'difficulty': filters.difficulty,
            'difficulty_min': filters.difficulty_min,
            'difficulty_max': filters.difficulty_max,
            'level': filters.level,
            'exclude_imported': filters.exclude_imported,
            'seed': filters.seed,
            'require_image': filters.require_image,
            'no_image': filters.no_image,
        },
        'source_root': str(source_root),
        'question_bank_path': str(question_bank_path),
        'total_source_questions': len(questions),
        'total_source_mcqs': len(source_mcqs),
        'matching_mcqs_before_duplicate_exclusion': len(matching_before_dedupe),
        'matching_mcqs_after_duplicate_exclusion': len(matching_after_source_dedupe),
        'selected': selected_rows,
        'duplicate_exclusions': duplicate_in_selection_exclusions + duplicate_import_exclusions,
        'skipped': skipped,
        'set': {
            'name': filters.set_name or default_set_name(filters),
            'slug': set_slug,
            'usable_in_classic': filters.usable_in_classic,
            'usable_in_boss_rush': filters.usable_in_boss_rush,
            'usable_as_recovery': filters.usable_as_recovery,
            'usable_in_team': filters.usable_in_team,
        },
    }


def select_pool(questions: list[dict], filters: ImportFilters, rng: random.Random) -> list[tuple[dict, str | None]]:
    if filters.per_subtopic_count is None:
        pool = list(questions)
        if filters.seed is not None:
            rng.shuffle(pool)
        return [
            (question, matched_subtopic(question, filters.subtopics))
            for question in pool
        ]

    selected = []
    selected_canonical_ids = set()
    for subtopic in filters.subtopics:
        candidates = [
            question
            for question in questions
            if subtopic in question_subtopics(question) and canonical_id_for(question) not in selected_canonical_ids
        ]
        if filters.seed is not None:
            rng.shuffle(candidates)
        if len(candidates) < filters.per_subtopic_count:
            raise ImportValidationError(
                f'Insufficient questions for subtopic {subtopic}: requested {filters.per_subtopic_count}, available {len(candidates)}.'
            )
        chosen = candidates[:filters.per_subtopic_count]
        selected.extend((question, subtopic) for question in chosen)
        selected_canonical_ids.update(canonical_id_for(question) for question in chosen)
    return selected


def build_selected_question_row(
    *,
    question: dict,
    assigned_subtopic: str | None,
    source_root: Path,
    question_bank_path: Path,
    static_root: Path,
    set_slug: str,
    requested_subtopics: tuple[str, ...],
) -> dict:
    canonical_id = canonical_id_for(question)
    answer_letter = source_answer_letter(question)
    options, has_explicit_options = normalize_options(question)
    text = normalize_question_text(question)
    uses_extracted_options = False
    if not has_explicit_options:
        text_without_options, extracted_options = extract_embedded_choice_options(text)
        if extracted_options:
            text = text_without_options
            options = extracted_options
            uses_extracted_options = True
    image_rows = []
    for index, image_ref in enumerate(question.get('images') or [], start=1):
        source_path = source_image_path(source_root, image_ref)
        suffix = source_path.suffix or '.png'
        destination_filename = f'{slugify(canonical_id)}__img{index:02d}{suffix.lower()}'
        static_relative_path = str(Path('images') / 'ib_physics' / set_slug / destination_filename).replace('\\', '/')
        image_rows.append({
            'source_ref': image_ref,
            'source_path': str(source_path),
            'exists': source_path.exists(),
            'static_relative_path': static_relative_path,
            'destination_path': str(static_root / static_relative_path),
        })

    return {
        'id': question.get('id'),
        'source_id': question.get('source_id'),
        'canonical_id': canonical_id,
        'title': title_for(question, requested_subtopics, assigned_subtopic),
        'topic_name': topic_name_for(question, requested_subtopics, assigned_subtopic),
        'matched_subtopic': matched_subtopic(question, requested_subtopics, assigned_subtopic),
        'text': text,
        'difficulty': question.get('difficulty') or 1,
        'level': question.get('level'),
        'available_for': question.get('available_for') or [],
        'has_explicit_options': has_explicit_options,
        'uses_extracted_options': uses_extracted_options,
        'uses_artificial_options': not has_explicit_options and not uses_extracted_options,
        'options': options,
        'correct_answer_letter': answer_letter,
        'images': image_rows,
        'source_bank_path': str(question_bank_path),
        'content_hash': question.get('content_hash'),
        'answer_hash': question.get('answer_hash'),
        'raw_metadata': source_metadata_values(question),
    }


def write_import_plan(plan: dict) -> dict:
    import_batch_id = uuid.uuid4().hex
    created_problem_ids = []
    copied_images = []
    try:
        problem_set = ProblemSet(
            name=plan['set']['name'],
            description='Imported from IB Physics Question System MCQ bank.',
            usable_in_classic=plan['set']['usable_in_classic'],
            usable_in_boss_rush=plan['set']['usable_in_boss_rush'],
            usable_as_recovery=plan['set']['usable_as_recovery'],
            usable_in_team=plan['set']['usable_in_team'],
        )
        db.session.add(problem_set)
        db.session.flush()

        for row in plan['selected']:
            topic = get_or_create_topic(row['topic_name'])
            problem = Problem(
                topic_id=topic.id,
                title=row['title'],
                prompt_text=row['text'],
                answer_text=correct_option_text(row),
                answer_type=PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
                difficulty=int(row['difficulty'] or 1),
                image_path=row['images'][0]['static_relative_path'] if row['images'] else None,
            )
            db.session.add(problem)
            db.session.flush()

            db.session.add(ProblemBlock(
                problem_id=problem.id,
                position=1,
                block_type=PROBLEM_BLOCK_TYPE_RICH_TEXT,
                text_content=row['text'],
            ))
            next_position = 2
            for image in row['images']:
                db.session.add(ProblemBlock(
                    problem_id=problem.id,
                    position=next_position,
                    block_type=PROBLEM_BLOCK_TYPE_IMAGE,
                    image_path=image['static_relative_path'],
                    image_width_pct=100,
                ))
                next_position += 1

            for position, option in enumerate(row['options'], start=1):
                db.session.add(ProblemChoiceOption(
                    problem_id=problem.id,
                    position=position,
                    option_text=option['text'],
                    is_correct=option['label'] == row['correct_answer_letter'],
                ))

            db.session.add(ProblemSourceMetadata(
                problem_id=problem.id,
                source_system=SOURCE_SYSTEM_IB_PHYSICS,
                source_bank_path=row['source_bank_path'],
                source_id=row['source_id'],
                canonical_id=row['canonical_id'],
                content_hash=row['content_hash'],
                answer_hash=row['answer_hash'],
                import_batch_id=import_batch_id,
                raw_metadata_json=row['raw_metadata'],
            ))
            problem_set.problems.append(problem)
            created_problem_ids.append(problem.id)

        copy_planned_images(plan, copied_images)
        db.session.commit()
        return {
            'problem_set_id': problem_set.id,
            'problem_ids': created_problem_ids,
            'import_batch_id': import_batch_id,
            'copied_images': copied_images,
        }
    except Exception:
        db.session.rollback()
        raise


def get_or_create_topic(name: str) -> Topic:
    topic = Topic.query.filter_by(name=name).first()
    if topic:
        return topic
    topic = Topic(name=name, subject='IB Physics', description='Imported IB Physics question bank subtopic.')
    db.session.add(topic)
    db.session.flush()
    return topic


def copy_planned_images(plan: dict, copied_images: list[str]) -> None:
    for row in plan['selected']:
        for image in row['images']:
            source = Path(image['source_path'])
            destination = Path(image['destination_path'])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied_images.append(str(destination))


def correct_option_text(row: dict) -> str:
    correct = next((option['text'] for option in row['options'] if option['label'] == row['correct_answer_letter']), '')
    if not correct:
        raise ImportValidationError(f'{row["canonical_id"]} has no option matching answer {row["correct_answer_letter"]}.')
    return correct


def _skip_row(question: dict, reason: str) -> dict:
    return {
        'id': question.get('id'),
        'source_id': question.get('source_id'),
        'canonical_id': canonical_id_for(question),
        'reason': reason,
    }


def default_set_name(filters: ImportFilters) -> str:
    joined = ', '.join(filters.subtopics)
    return f'IB Physics MCQ {joined}'


def slugify(value: str) -> str:
    value = re.sub(r'[^A-Za-z0-9._-]+', '-', value.strip())
    value = value.strip('-._').lower()
    return value[:80] or 'ib-physics-mcq'


def format_plan_report(plan: dict, *, dry_run: bool) -> str:
    lines = []
    lines.append('IB Physics MCQ Import Report')
    lines.append('=' * 28)
    lines.append(f'Mode: {"dry-run" if dry_run else "write"}')
    lines.append(f'Question bank: {plan["question_bank_path"]}')
    lines.append(f'Requested filters: {json.dumps(plan["filters"], ensure_ascii=False, sort_keys=True)}')
    lines.append(f'Total source questions: {plan["total_source_questions"]}')
    lines.append(f'Total source MCQs (type=mcq, paper=Paper 1A): {plan["total_source_mcqs"]}')
    lines.append(f'Matching before duplicate exclusion: {plan["matching_mcqs_before_duplicate_exclusion"]}')
    lines.append(f'Matching after duplicate exclusion: {plan["matching_mcqs_after_duplicate_exclusion"]}')
    lines.append(f'Planned ProblemSet: {plan["set"]["name"]}')
    lines.append(
        'Mode flags: '
        f'classic={plan["set"]["usable_in_classic"]}, '
        f'boss_rush_attack={plan["set"]["usable_in_boss_rush"]}, '
        f'recovery={plan["set"]["usable_as_recovery"]}, '
        f'team={plan["set"]["usable_in_team"]}'
    )
    lines.append('')
    lines.append('Selected questions:')
    for index, row in enumerate(plan['selected'], start=1):
        lines.append(
            f'  {index}. {row["title"]} | canonical={row["canonical_id"]} | '
            f'source_id={row["source_id"]} | topic={row["topic_name"]} | '
            f'difficulty={row["difficulty"]} | level={row["level"]} | '
            f'options={"explicit" if row["has_explicit_options"] else "artificial A/B/C/D"} | '
            f'answer={row["correct_answer_letter"]} | images={len(row["images"])}'
        )
        for image in row['images']:
            lines.append(
                f'     image: {image["source_ref"]} | exists={image["exists"]} | '
                f'copy_to={image["static_relative_path"]}'
            )
    lines.append('')
    lines.append(f'Duplicate exclusions: {len(plan["duplicate_exclusions"])}')
    for row in plan['duplicate_exclusions'][:20]:
        lines.append(f'  - {row["canonical_id"]}: {row["reason"]}')
    if len(plan['duplicate_exclusions']) > 20:
        lines.append(f'  ... {len(plan["duplicate_exclusions"]) - 20} more')
    lines.append(f'Skipped selected questions: {len(plan["skipped"])}')
    for row in plan['skipped']:
        lines.append(f'  - {row["canonical_id"]}: {row["reason"]}')
    return '\n'.join(lines)


def parse_import_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Import IB Physics Paper 1A MCQs into math_game_v2 problem sets.')
    parser.add_argument('--source-root', default=DEFAULT_SOURCE_ROOT)
    parser.add_argument('--question-bank', default=DEFAULT_QUESTION_BANK)
    parser.add_argument('--subtopic', action='append', default=[], help='Repeatable source subtopic code, e.g. C.1')
    parser.add_argument('--count', type=int, required=True)
    parser.add_argument('--per-subtopic-count', type=int)
    parser.add_argument('--difficulty', type=int)
    parser.add_argument('--difficulty-min', type=int)
    parser.add_argument('--difficulty-max', type=int)
    parser.add_argument('--level')
    parser.add_argument('--exclude-imported', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--seed', type=int)
    parser.add_argument('--set-name')
    parser.add_argument('--dry-run', action='store_true', default=False)
    parser.add_argument('--write', action='store_true', default=False)
    parser.add_argument('--require-image', action='store_true', default=False)
    parser.add_argument('--no-image', action='store_true', default=False)
    parser.add_argument('--classic', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--boss-rush-attack', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--boss-rush-recovery', action='store_true', default=False)
    parser.add_argument('--team', action='store_true', default=False)
    args = parser.parse_args(argv)
    if args.write and args.dry_run:
        parser.error('Choose either --write or --dry-run, not both.')
    return args


def filters_from_args(args: argparse.Namespace) -> ImportFilters:
    return ImportFilters(
        subtopics=tuple(args.subtopic),
        count=args.count,
        per_subtopic_count=args.per_subtopic_count,
        difficulty=args.difficulty,
        difficulty_min=args.difficulty_min,
        difficulty_max=args.difficulty_max,
        level=args.level,
        exclude_imported=args.exclude_imported,
        seed=args.seed,
        require_image=args.require_image,
        no_image=args.no_image,
        set_name=args.set_name,
        usable_in_classic=args.classic,
        usable_in_boss_rush=args.boss_rush_attack,
        usable_as_recovery=args.boss_rush_recovery,
        usable_in_team=args.team,
    )
