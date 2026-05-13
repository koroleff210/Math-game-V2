import argparse
import html
import json
import random
import re
import shutil
import uuid
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from sqlalchemy import inspect as sa_inspect, text

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
from app.models.subjects import Subject


SOURCE_SYSTEM_IB_PHYSICS = 'ib_physics_question_system'
DEFAULT_SOURCE_ROOT = r'C:\Users\korol\OneDrive\Desktop\IB Physics Question System'
DEFAULT_QUESTION_BANK = r'data\complete_questionbank\questions.json'
IB_PHYSICS_IMAGE_ROOT = Path('data') / 'complete_questionbank' / 'images'
MCQ_LABELS = ('A', 'B', 'C', 'D')
SUPERSCRIPT_MAP = {
    '0': '⁰',
    '1': '¹',
    '2': '²',
    '3': '³',
    '4': '⁴',
    '5': '⁵',
    '6': '⁶',
    '7': '⁷',
    '8': '⁸',
    '9': '⁹',
    '+': '⁺',
    '-': '⁻',
    '=': '⁼',
    '(': '⁽',
    ')': '⁾',
    'n': 'ⁿ',
    'i': 'ⁱ',
}
SUBSCRIPT_MAP = {
    '0': '₀',
    '1': '₁',
    '2': '₂',
    '3': '₃',
    '4': '₄',
    '5': '₅',
    '6': '₆',
    '7': '₇',
    '8': '₈',
    '9': '₉',
    '+': '₊',
    '-': '₋',
    '=': '₌',
    '(': '₍',
    ')': '₎',
}


class ImportValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ImportFilters:
    subtopics: tuple[str, ...]
    count: int
    all_matching: bool = False
    per_subtopic_count: int | None = None
    difficulty: int | None = None
    difficulty_min: int | None = None
    difficulty_max: int | None = None
    level: str | None = None
    exclude_imported: bool = True
    seed: int | None = None
    require_image: bool = False
    no_image: bool = False
    strict_subtopic_list: bool = False
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


def question_filter_subtopics(question: dict, *, strict_subtopic_list: bool = False) -> set[str]:
    if not strict_subtopic_list:
        return question_subtopics(question)
    return {str(raw).strip() for raw in (question.get('subtopics') or []) if raw}


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


def normalize_question_text(question: dict, *, strip_mcq_options_from_html: bool = False) -> str:
    raw = question.get('question_text')
    html_source = question.get('question_html') or ''
    html_has_super_or_sub = bool(re.search(r'<\s*/?\s*(sup|sub)\b', html_source, flags=re.IGNORECASE))
    html_without_options = remove_mcq_option_list_from_html(html_source) if strip_mcq_options_from_html else html_source
    html_text = html_to_text(html_without_options)
    if not raw:
        raw = html_text
    elif strip_mcq_options_from_html and html_text.strip():
        raw = html_text
    elif html_has_super_or_sub:
        # Source text often loses exponent formatting; when HTML has sup/sub we prefer
        # the HTML-derived text for readable physics notation.
        raw = html_text
    text = str(raw or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    lines = [line for line in text.split('\n') if line.strip() != '[image]']
    return normalize_embedded_mcq_text(normalize_unit_notation('\n'.join(lines))).strip()


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


def _render_superscript_text(raw: str) -> str:
    compact = re.sub(r'\s+', '', html.unescape(raw or '')).replace('−', '-')
    if compact and re.fullmatch(r'[.,;:!?]+', compact):
        return compact
    if compact and all(char in SUPERSCRIPT_MAP for char in compact):
        return ''.join(SUPERSCRIPT_MAP[char] for char in compact)
    return '^' + compact if compact else ''


def _render_subscript_text(raw: str) -> str:
    compact = re.sub(r'\s+', '', html.unescape(raw or ''))
    if compact and re.fullmatch(r'[.,;:!?]+', compact):
        return compact
    if compact and all(char in SUBSCRIPT_MAP for char in compact):
        return ''.join(SUBSCRIPT_MAP[char] for char in compact)
    return f'_{{{compact}}}' if compact else ''


def remove_mcq_option_list_from_html(source: str) -> str:
    if not source:
        return ''
    return _replace_mcq_option_lists(source, '')


def _replace_mcq_option_lists(source: str, replacement) -> str:
    def replace_if_mcq_list(match):
        list_body = match.group(2)
        item_count = len(re.findall(r'<\s*li\b', list_body, flags=re.IGNORECASE))
        has_mcq_class = bool(re.search(r'mcq-options', match.group(0), flags=re.IGNORECASE))
        if has_mcq_class or item_count == 4:
            return replacement(match) if callable(replacement) else replacement
        return match.group(0)

    return re.sub(
        r'<\s*(ol|ul)\b[^>]*>(.*?)<\s*/\s*(ol|ul)\s*>',
        replace_if_mcq_list,
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )


def normalize_unit_notation(text: str) -> str:
    if not text:
        return ''
    normalized = text
    normalized = re.sub(r'(?<![A-Za-z])((?:m|mm|cm|km|nm|μm|um))(2|3)\b', lambda m: m.group(1) + _render_superscript_text(m.group(2)), normalized)
    normalized = re.sub(r'\b([A-Za-zΩμ]+)-([123])\b', lambda m: f'{m.group(1)}{_render_superscript_text("-" + m.group(2))}', normalized)
    normalized = re.sub(r'\bkg\s*m-3\b', f'kg m{_render_superscript_text("-3")}', normalized)
    normalized = re.sub(r'\bkgm-3\b', f'kgm{_render_superscript_text("-3")}', normalized)
    return normalized


class _ProblemHtmlTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0
        self.math_depth = 0
        self.annotation_depth = 0
        self.annotation_parts = []
        self.sup_depth = 0
        self.sup_parts = []
        self.sub_depth = 0
        self.sub_parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = {key.lower(): value or '' for key, value in attrs}

        if self.skip_depth:
            self.skip_depth += 1
            return

        if self.math_depth:
            self.math_depth += 1
            if tag == 'annotation':
                self.annotation_depth = 1
                self.annotation_parts = []
            return

        data_latex = attrs_dict.get('data-latex')
        if data_latex:
            self.parts.append(f'${html.unescape(data_latex)}$')
            self.skip_depth = 1
            return

        class_text = attrs_dict.get('class', '')
        if tag in {'script', 'style', 'picture'} or attrs_dict.get('aria-hidden', '').lower() == 'true' or 'katex-html' in class_text:
            self.skip_depth = 1
            return
        if tag == 'img':
            return
        if tag == 'math':
            self.math_depth = 1
            return
        if tag == 'sup':
            self.sup_depth = 1
            self.sup_parts = []
            return
        if tag == 'sub':
            self.sub_depth = 1
            self.sub_parts = []
            return
        if tag == 'br':
            self.parts.append('\n')
        elif tag in {'p', 'div', 'li', 'tr', 'table', 'ol', 'ul'}:
            self._soft_newline()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if self.annotation_depth:
            if tag == 'annotation':
                self.parts.append(f'${html.unescape("".join(self.annotation_parts).strip())}$')
                self.annotation_depth = 0
                self.annotation_parts = []
            return
        if self.math_depth:
            self.math_depth -= 1
            return
        if self.sup_depth:
            if tag == 'sup':
                self.parts.append(_render_superscript_text(''.join(self.sup_parts)))
                self.sup_depth = 0
                self.sup_parts = []
            return
        if self.sub_depth:
            if tag == 'sub':
                self.parts.append(_render_subscript_text(''.join(self.sub_parts)))
                self.sub_depth = 0
                self.sub_parts = []
            return
        if tag in {'p', 'div', 'li', 'tr', 'table', 'ol', 'ul'}:
            self._soft_newline()

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.annotation_depth:
            self.annotation_parts.append(data)
            return
        if self.math_depth:
            return
        if self.sup_depth:
            self.sup_parts.append(data)
            return
        if self.sub_depth:
            self.sub_parts.append(data)
            return
        self.parts.append(data)

    def _soft_newline(self):
        if self.parts and not self.parts[-1].endswith('\n'):
            self.parts.append('\n')

    def text(self):
        text = ''.join(self.parts)
        lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines()]
        return '\n'.join(line for line in lines if line).strip()


def html_to_text(source: str) -> str:
    parser = _ProblemHtmlTextExtractor()
    parser.feed(source or '')
    parser.close()
    return normalize_unit_notation(parser.text())


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
    omega_choices = extract_trailing_number_unit_choice_options(source)
    if omega_choices[1]:
        return omega_choices

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


def extract_trailing_number_unit_choice_options(text: str) -> tuple[str, list[dict]]:
    stem_end = trailing_choice_stem_end(text)
    if stem_end < max(10, len(text) // 5):
        return text, []
    stem = text[:stem_end + 1].strip()
    tail = text[stem_end + 1:].strip()
    if not tail:
        return text, []

    pattern = re.compile(
        r'(?<!\S)([+-]?\d+(?:\.\d+)?(?:\s*[×x]\s*10(?:\^?[+-]?\d+|[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+))?)\s*(\$\s*\\[A-Za-z]+\s*\$|\\[A-Za-z]+|[A-Za-zΩμ°]+)'
    )
    matches = list(pattern.finditer(tail))
    if len(matches) != 4:
        return text, []
    rebuilt = ' '.join(tail[m.start():m.end()].strip() for m in matches)
    if re.sub(r'\s+', ' ', tail).strip() != re.sub(r'\s+', ' ', rebuilt).strip():
        return text, []
    options = [tail[m.start():m.end()].strip() for m in matches]
    if all(options):
        return stem, _make_choice_options(options)
    return text, []


def extract_choice_options_from_html(question_html: str) -> list[dict]:
    if not question_html:
        return []
    for list_match in re.finditer(
        r'<\s*(ol|ul)\b[^>]*>(.*?)<\s*/\s*(ol|ul)\s*>',
        question_html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        list_body = list_match.group(2)
        has_mcq_class = bool(re.search(r'mcq-options', list_match.group(0), flags=re.IGNORECASE))
        options = []
        for li in re.finditer(r'<\s*li\b[^>]*>(.*?)<\s*/\s*li\s*>', list_body, flags=re.IGNORECASE | re.DOTALL):
            option_text = html_to_text(li.group(1)).strip()
            option_text = re.sub(r'^[A-D]\s*[\.\)]\s*', '', option_text)
            if option_text:
                options.append(option_text)
        if len(options) == 4 and (has_mcq_class or options):
            return _make_choice_options(options)
    return []


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
    if filters.count < 1 and not filters.all_matching:
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
        if not (question_filter_subtopics(question, strict_subtopic_list=filters.strict_subtopic_list) & set(filters.subtopics)):
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

    target_count = len(pool) if filters.all_matching else filters.count
    if len(pool) < target_count:
        raise ImportValidationError(
            f'Insufficient questions after filters and duplicate exclusion: requested {target_count}, available {len(pool)}.'
        )

    selected = pool[:target_count]
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
            'count': target_count,
            'all_matching': filters.all_matching,
            'per_subtopic_count': filters.per_subtopic_count,
            'difficulty': filters.difficulty,
            'difficulty_min': filters.difficulty_min,
            'difficulty_max': filters.difficulty_max,
            'level': filters.level,
            'exclude_imported': filters.exclude_imported,
            'seed': filters.seed,
            'require_image': filters.require_image,
            'no_image': filters.no_image,
            'strict_subtopic_list': filters.strict_subtopic_list,
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
            if subtopic in question_filter_subtopics(question, strict_subtopic_list=filters.strict_subtopic_list)
            and canonical_id_for(question) not in selected_canonical_ids
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
    text = normalize_question_text(question, strip_mcq_options_from_html=has_explicit_options)
    uses_extracted_options = False
    option_strategy = 'explicit' if has_explicit_options else 'artificial'
    if not has_explicit_options:
        html_options = extract_choice_options_from_html(question.get('question_html') or '')
        if html_options:
            options = html_options
            text = normalize_question_text(question, strip_mcq_options_from_html=True)
            uses_extracted_options = True
            option_strategy = 'extracted_html'
        text_without_options, extracted_options = extract_embedded_choice_options(text)
        if extracted_options and not uses_extracted_options:
            text = text_without_options
            options = extracted_options
            uses_extracted_options = True
            option_strategy = 'extracted_text'
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
        'option_strategy': option_strategy,
        'options': options,
        'correct_answer_letter': answer_letter,
        'images': image_rows,
        'source_bank_path': str(question_bank_path),
        'content_hash': question.get('content_hash'),
        'answer_hash': question.get('answer_hash'),
        'raw_metadata': source_metadata_values(question),
    }


def get_or_create_subject(name: str) -> Subject:
    subject = Subject.query.filter_by(name=name).first()
    if subject:
        return subject
    subject = Subject(name=name)
    db.session.add(subject)
    db.session.flush()
    return subject


def get_or_create_topic(name: str, *, subject: Subject | None = None) -> Topic:
    topic = Topic.query.filter_by(name=name).first()
    if topic:
        if subject and topic.subject_id != subject.id:
            topic.subject_id = subject.id
            topic.subject = subject.name
        return topic
    topic = Topic(
        name=name,
        subject=subject.name if subject else 'IB Physics',
        subject_id=subject.id if subject else None,
        description='Imported IB Physics question bank subtopic.',
    )
    db.session.add(topic)
    db.session.flush()
    return topic


def write_import_plan(
    plan: dict,
    *,
    library_only: bool = False,
    subject_name: str | None = None,
    topic_name: str | None = None,
) -> dict:
    import_batch_id = uuid.uuid4().hex
    created_problem_ids = []
    copied_images = []
    try:
        subject = get_or_create_subject(subject_name) if subject_name else None
        fixed_topic = get_or_create_topic(topic_name, subject=subject) if topic_name else None
        problem_set = None
        if not library_only:
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
            topic = fixed_topic or get_or_create_topic(row['topic_name'], subject=subject)
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
            if problem_set is not None:
                problem_set.problems.append(problem)
            created_problem_ids.append(problem.id)

        copy_planned_images(plan, copied_images)
        db.session.commit()
        return {
            'problem_set_id': problem_set.id if problem_set is not None else None,
            'problem_ids': created_problem_ids,
            'import_batch_id': import_batch_id,
            'copied_images': copied_images,
        }
    except Exception:
        db.session.rollback()
        raise


def _source_questions_by_canonical(source_root: str | Path, question_bank: str | Path) -> dict[str, dict]:
    questions = load_source_bank(source_root, question_bank)
    lookup = {}
    for question in questions:
        canonical = canonical_id_for(question)
        if canonical not in lookup:
            lookup[canonical] = question
    return lookup


def _imported_ib_problem_rows() -> list[tuple[Problem, ProblemSourceMetadata]]:
    return (
        db.session.query(Problem, ProblemSourceMetadata)
        .join(ProblemSourceMetadata, ProblemSourceMetadata.problem_id == Problem.id)
        .filter(ProblemSourceMetadata.source_system == SOURCE_SYSTEM_IB_PHYSICS)
        .all()
    )


def _problem_rich_text_block(problem: Problem) -> ProblemBlock | None:
    for block in sorted(problem.blocks, key=lambda row: row.position):
        if block.block_type == PROBLEM_BLOCK_TYPE_RICH_TEXT:
            return block
    return None


def _problem_choice_texts(problem: Problem) -> list[str]:
    return [row.option_text for row in sorted(problem.choice_options, key=lambda item: item.position)]


def _is_artificial_abcd(problem: Problem) -> bool:
    return _problem_choice_texts(problem) == list(MCQ_LABELS)


def _build_repaired_import_row(problem: Problem, metadata: ProblemSourceMetadata, source_question: dict) -> dict:
    answer_letter = source_answer_letter(source_question)
    options, has_explicit_options = normalize_options(source_question)
    mode = 'explicit'
    repaired_text = normalize_question_text(source_question, strip_mcq_options_from_html=has_explicit_options)

    if not has_explicit_options:
        html_options = extract_choice_options_from_html(source_question.get('question_html') or '')
        if html_options:
            options = html_options
            repaired_text = normalize_question_text(source_question, strip_mcq_options_from_html=True)
            mode = 'extracted_html'
        else:
            text_without_options, extracted_options = extract_embedded_choice_options(repaired_text)
            if extracted_options:
                repaired_text = text_without_options
                options = extracted_options
                mode = 'extracted_text'
            else:
                mode = 'artificial'

    corrected_answer_text = next((row['text'] for row in options if row['label'] == answer_letter), '')
    if not corrected_answer_text:
        raise ImportValidationError(f'{metadata.canonical_id} has no option matching answer {answer_letter} during repair.')

    current_text = (_problem_rich_text_block(problem).text_content if _problem_rich_text_block(problem) else problem.prompt_text) or ''
    current_options = _problem_choice_texts(problem)
    target_options = [row['text'] for row in options]

    return {
        'problem_id': problem.id,
        'canonical_id': metadata.canonical_id,
        'title': problem.title,
        'mode': mode,
        'old_text': current_text,
        'new_text': repaired_text,
        'old_options': current_options,
        'new_options': target_options,
        'answer_letter': answer_letter,
        'new_answer_text': corrected_answer_text,
        'text_changed': current_text != repaired_text,
        'options_changed': current_options != target_options,
        'has_images': any(block.block_type == PROBLEM_BLOCK_TYPE_IMAGE for block in problem.blocks),
    }


def audit_imported_ib_physics_quality(source_root: str | Path, question_bank: str | Path) -> dict:
    source_lookup = _source_questions_by_canonical(source_root, question_bank)
    rows = _imported_ib_problem_rows()
    suspicious_patterns = ('mm2', 'cm2', 'm2', 's-1', 'm-1', 'kg m-3', 'kgm-3', 'ms-1')
    suspicious_counts = {key: 0 for key in suspicious_patterns}
    artificial_with_embedded = 0
    examples = []

    for problem, metadata in rows:
        body = (_problem_rich_text_block(problem).text_content if _problem_rich_text_block(problem) else problem.prompt_text) or ''
        for pattern in suspicious_patterns:
            if pattern in body:
                suspicious_counts[pattern] += 1

        is_artificial = _is_artificial_abcd(problem)
        if is_artificial:
            _, extracted = extract_embedded_choice_options(body)
            if extracted:
                artificial_with_embedded += 1
                if len(examples) < 5:
                    source_question = source_lookup.get(metadata.canonical_id, {})
                    examples.append({
                        'title': problem.title,
                        'canonical_id': metadata.canonical_id,
                        'body_excerpt': body[:420],
                        'source_question_text_excerpt': (source_question.get('question_text') or '')[:300],
                        'source_question_html_excerpt': (source_question.get('question_html') or '')[:420],
                        'game_options': _problem_choice_texts(problem),
                        'source_options': source_question.get('options'),
                    })

    return {
        'total_imported_ib': len(rows),
        'artificial_abcd': sum(1 for problem, _ in rows if _is_artificial_abcd(problem)),
        'explicit_or_extracted_options': sum(1 for problem, _ in rows if not _is_artificial_abcd(problem)),
        'suspicious_notation_counts': suspicious_counts,
        'artificial_with_likely_embedded_options': artificial_with_embedded,
        'examples': examples,
    }


def plan_repair_imported_ib_physics_quality(source_root: str | Path, question_bank: str | Path) -> dict:
    source_lookup = _source_questions_by_canonical(source_root, question_bank)
    rows = _imported_ib_problem_rows()
    updates = []
    warnings = []

    for problem, metadata in rows:
        source_question = source_lookup.get(metadata.canonical_id)
        if not source_question:
            warnings.append({
                'problem_id': problem.id,
                'canonical_id': metadata.canonical_id,
                'reason': 'source question not found by canonical_id',
            })
            continue
        row = _build_repaired_import_row(problem, metadata, source_question)
        if row['text_changed'] or row['options_changed'] or (problem.answer_text != row['new_answer_text']):
            updates.append(row)

    return {
        'total_imported_ib': len(rows),
        'planned_updates': len(updates),
        'warnings': warnings,
        'updates': updates,
    }


def apply_repair_imported_ib_physics_quality(plan: dict) -> dict:
    updated_problem_ids = []
    try:
        for row in plan.get('updates', []):
            problem = db.session.get(Problem, row['problem_id'])
            if not problem:
                continue
            problem.prompt_text = row['new_text']
            problem.answer_text = row['new_answer_text']
            rich_text = _problem_rich_text_block(problem)
            if rich_text:
                rich_text.text_content = row['new_text']
            else:
                db.session.add(ProblemBlock(
                    problem_id=problem.id,
                    position=1,
                    block_type=PROBLEM_BLOCK_TYPE_RICH_TEXT,
                    text_content=row['new_text'],
                ))
            ProblemChoiceOption.query.filter_by(problem_id=problem.id).delete()
            for idx, option_text in enumerate(row['new_options'], start=1):
                db.session.add(ProblemChoiceOption(
                    problem_id=problem.id,
                    position=idx,
                    option_text=option_text,
                    is_correct=option_text == row['new_answer_text'],
                ))
            updated_problem_ids.append(problem.id)
        db.session.commit()
        return {
            'updated_problem_ids': updated_problem_ids,
            'updated_count': len(updated_problem_ids),
        }
    except Exception:
        db.session.rollback()
        raise

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


RUNTIME_DEPENDENCY_TABLES = (
    'analytics_boss_rush_battle_event',
    'analytics_classic_economy_event',
    'analytics_answer_attempt',
    'analytics_player_problem',
    'analytics_player_round',
    'analytics_round_problem',
    'analytics_round',
    'round_player_result',
    'round_history',
    'boss_rush_problem_attempt',
    'boss_rush_player_state',
    'boss_rush_round_config',
    'player_answer',
    'problem_solver_count',
    'player_problem_state',
    'classic_round_config',
    'round_player',
    'game_round',
    'game_session',
)

PROBLEM_LIBRARY_TABLES = (
    'problem_set_problems',
    'problem_source_metadata',
    'problem_choice_option',
    'problem_accepted_answer',
    'problem_block',
    'problem',
    'problem_set',
    'topic',
    'subject',
)


def table_count(table_name: str) -> int:
    return db.session.execute(text(f'SELECT COUNT(*) FROM {table_name}')).scalar() or 0


def existing_table_counts(table_names: tuple[str, ...]) -> dict[str, int]:
    inspector = sa_inspect(db.engine)
    existing = set(inspector.get_table_names())
    return {
        table_name: table_count(table_name)
        for table_name in table_names
        if table_name in existing
    }


def content_reset_blockers() -> dict[str, int]:
    return {
        table_name: count
        for table_name, count in existing_table_counts(RUNTIME_DEPENDENCY_TABLES).items()
        if count
    }


def reset_problem_library_content(*, clear_runtime_dependencies: bool = False) -> dict:
    blockers = content_reset_blockers()
    if blockers and not clear_runtime_dependencies:
        raise ImportValidationError(
            'Problem content reset is blocked by dependent runtime/history/analytics rows: '
            + ', '.join(f'{table}={count}' for table, count in blockers.items())
        )

    before = existing_table_counts(RUNTIME_DEPENDENCY_TABLES + PROBLEM_LIBRARY_TABLES)
    deleted = {}
    try:
        if clear_runtime_dependencies:
            for table_name in RUNTIME_DEPENDENCY_TABLES:
                if table_name in before:
                    db.session.execute(text(f'DELETE FROM {table_name}'))
                    deleted[table_name] = before[table_name]
        for table_name in PROBLEM_LIBRARY_TABLES:
            if table_name in before:
                db.session.execute(text(f'DELETE FROM {table_name}'))
                deleted[table_name] = before[table_name]
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    after = existing_table_counts(RUNTIME_DEPENDENCY_TABLES + PROBLEM_LIBRARY_TABLES)
    return {
        'before': before,
        'after': after,
        'deleted': deleted,
        'cleared_runtime_dependencies': clear_runtime_dependencies,
    }


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
            f'options={row.get("option_strategy") or ("explicit" if row["has_explicit_options"] else "artificial A/B/C/D")} | '
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


def format_quality_audit_report(audit: dict) -> str:
    lines = []
    lines.append('IB Physics Imported Quality Audit')
    lines.append('=' * 33)
    lines.append(f'Total imported IB problems: {audit["total_imported_ib"]}')
    lines.append(f'Artificial A/B/C/D options: {audit["artificial_abcd"]}')
    lines.append(f'Explicit or extracted options: {audit["explicit_or_extracted_options"]}')
    lines.append(f'Artificial options with likely embedded choices: {audit["artificial_with_likely_embedded_options"]}')
    lines.append('Suspicious notation counts:')
    for key, value in audit['suspicious_notation_counts'].items():
        lines.append(f'  - {key}: {value}')
    if audit.get('examples'):
        lines.append('')
        lines.append('Examples:')
        for idx, item in enumerate(audit['examples'], start=1):
            lines.append(f'  {idx}. {item["title"]} ({item["canonical_id"]})')
            lines.append(f'     body: {item["body_excerpt"][:180]}')
    return '\n'.join(lines)


def format_repair_plan_report(plan: dict, *, dry_run: bool) -> str:
    lines = []
    lines.append('IB Physics Imported Quality Repair Plan')
    lines.append('=' * 39)
    lines.append(f'Mode: {"dry-run" if dry_run else "write"}')
    lines.append(f'Total imported IB problems: {plan["total_imported_ib"]}')
    lines.append(f'Planned updates: {plan["planned_updates"]}')
    lines.append(f'Warnings: {len(plan["warnings"])}')
    if plan['warnings']:
        for warning in plan['warnings'][:20]:
            lines.append(f'  - warning {warning["canonical_id"]}: {warning["reason"]}')
    if plan['updates']:
        lines.append('')
        lines.append('Update candidates:')
        for idx, row in enumerate(plan['updates'][:50], start=1):
            lines.append(
                f'  {idx}. {row["title"]} | canonical={row["canonical_id"]} | '
                f'mode={row["mode"]} | text_changed={row["text_changed"]} | '
                f'options_changed={row["options_changed"]}'
            )
        if len(plan['updates']) > 50:
            lines.append(f'  ... {len(plan["updates"]) - 50} more')
    return '\n'.join(lines)


def parse_import_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Import IB Physics Paper 1A MCQs into math_game_v2 problem sets.')
    parser.add_argument('--audit-imported-quality', action='store_true', default=False)
    parser.add_argument('--repair-imported-quality', action='store_true', default=False)
    parser.add_argument('--source-root', default=DEFAULT_SOURCE_ROOT)
    parser.add_argument('--question-bank', default=DEFAULT_QUESTION_BANK)
    parser.add_argument('--subtopic', action='append', default=[], help='Repeatable source subtopic code, e.g. C.1')
    parser.add_argument('--count', type=int, default=0)
    parser.add_argument('--all-matching', action='store_true', default=False)
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
    parser.add_argument('--strict-subtopic-list', action='store_true', default=False)
    parser.add_argument('--library-only', action='store_true', default=False)
    parser.add_argument('--subject-name')
    parser.add_argument('--topic-name')
    parser.add_argument('--classic', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--boss-rush-attack', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--boss-rush-recovery', action='store_true', default=False)
    parser.add_argument('--team', action='store_true', default=False)
    args = parser.parse_args(argv)
    if args.write and args.dry_run:
        parser.error('Choose either --write or --dry-run, not both.')
    if args.audit_imported_quality and args.repair_imported_quality:
        parser.error('Use either --audit-imported-quality or --repair-imported-quality, not both.')
    return args


def filters_from_args(args: argparse.Namespace) -> ImportFilters:
    return ImportFilters(
        subtopics=tuple(args.subtopic),
        count=args.count,
        all_matching=args.all_matching,
        per_subtopic_count=args.per_subtopic_count,
        difficulty=args.difficulty,
        difficulty_min=args.difficulty_min,
        difficulty_max=args.difficulty_max,
        level=args.level,
        exclude_imported=args.exclude_imported,
        seed=args.seed,
        require_image=args.require_image,
        no_image=args.no_image,
        strict_subtopic_list=args.strict_subtopic_list,
        set_name=args.set_name,
        usable_in_classic=args.classic,
        usable_in_boss_rush=args.boss_rush_attack,
        usable_as_recovery=args.boss_rush_recovery,
        usable_in_team=args.team,
    )
