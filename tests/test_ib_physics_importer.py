import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
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
from app.services.ib_physics_importer import (
    ImportFilters,
    build_import_plan,
    extract_embedded_choice_options,
    is_canonical_mcq,
    normalize_embedded_mcq_text,
    normalize_options,
    write_import_plan,
)


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'ib-physics-importer-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


flask_app = create_app(_TestConfig)

passed = 0
failed = 0


def check(label, condition, detail=''):
    global passed, failed
    if condition:
        print(f'  PASS  {label}')
        passed += 1
    else:
        msg = f'  FAIL  {label}'
        if detail:
            msg += f'  ({detail})'
        print(msg)
        failed += 1


def _question(
    *,
    qid,
    canonical_id,
    subtopics,
    answer='B',
    paper='Paper 1A',
    qtype='mcq',
    options=None,
    images=None,
    difficulty=2,
    level='SL',
    text=None,
):
    return {
        'id': qid,
        'source_id': f'SRC-{qid}',
        'canonical_id': canonical_id,
        'paper': paper,
        'type': qtype,
        'question_text': text or 'A wave has wavelength λ and angle θ. Calculate ΔV across 5 Ω using 3 μC ×10^2.',
        'options': options if options is not None else [
            {'label': 'A', 'text': '1 Ω'},
            {'label': 'B', 'text': '2 Ω'},
            {'label': 'C', 'text': '3 Ω'},
            {'label': 'D', 'text': '4 Ω'},
        ],
        'answer': answer,
        'images': images or [],
        'subtopics': subtopics,
        'subtopic_titles': {
            'C.1': 'Simple harmonic motion',
            'C.2': 'Wave model',
            'C.3': 'Wave phenomena',
        },
        'primary_subtopic': subtopics[0] if subtopics else None,
        'difficulty': difficulty,
        'level': level,
        'available_for': ['SL', 'HL'] if level == 'SL' else ['HL'],
        'content_hash': f'content-{canonical_id}',
        'answer_hash': f'answer-{answer}',
    }


def _write_fixture_bank(root: Path):
    image_dir = root / 'data' / 'complete_questionbank' / 'images' / 'fixtures'
    image_dir.mkdir(parents=True)
    (image_dir / 'diagram.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
    questions = [
        _question(qid='Paper1A-Q001', canonical_id='canon-1', subtopics=['C.1'], difficulty=2, level='SL'),
        _question(qid='Paper1A-Q002', canonical_id='canon-2', subtopics=['C.2'], difficulty=3, level='HL', options=[]),
        _question(qid='Paper1A-Q003', canonical_id='canon-3', subtopics=['C.1', 'C.2'], difficulty=4, level='SL', images=['fixtures/diagram.png']),
        _question(qid='Paper1A-Q004', canonical_id='canon-3', subtopics=['C.2'], difficulty=4, level='SL'),
        _question(qid='Paper1B-Q005', canonical_id='canon-paper-1b', subtopics=['C.1'], paper='Paper 1B'),
        _question(qid='Paper2-Q006', canonical_id='canon-structured', subtopics=['C.1'], paper='Paper 2', qtype='structured'),
    ]
    bank = root / 'data' / 'complete_questionbank' / 'questions.json'
    bank.write_text(json.dumps({'questions': questions}, ensure_ascii=False), encoding='utf-8')
    return bank


def _filters(**overrides):
    values = {
        'subtopics': ('C.1',),
        'count': 1,
        'exclude_imported': True,
        'seed': None,
    }
    values.update(overrides)
    return ImportFilters(**values)


def _build_plan(root: Path, static_root: Path, filters: ImportFilters):
    return build_import_plan(
        source_root=root,
        question_bank='data/complete_questionbank/questions.json',
        filters=filters,
        static_root=static_root,
    )


def run_tests():
    with tempfile.TemporaryDirectory() as source_tmp, tempfile.TemporaryDirectory() as static_tmp:
        source_root = Path(source_tmp)
        static_root = Path(static_tmp)
        _write_fixture_bank(source_root)

        with flask_app.app_context():
            db.drop_all()
            db.create_all()

            check('IBP-01: MCQ filter requires type=mcq and Paper 1A', is_canonical_mcq({
                'type': 'mcq',
                'paper': 'Paper 1A',
            }) and not is_canonical_mcq({'type': 'structured', 'paper': 'Paper 1A'})
               and not is_canonical_mcq({'type': 'mcq', 'paper': 'Paper 1B'}))

            plan = _build_plan(source_root, static_root, _filters(subtopics=('C.1', 'C.2'), count=3))
            selected_ids = [row['canonical_id'] for row in plan['selected']]
            check('IBP-02: multiple subtopic filter selects across requested subtopics', {'canon-1', 'canon-2', 'canon-3'} == set(selected_ids))
            check('IBP-03: duplicate canonical_id across selected subtopics is selected once', selected_ids.count('canon-3') == 1)

            explicit_options, explicit = normalize_options(_question(qid='Paper1A-Q010', canonical_id='canon-10', subtopics=['C.1']))
            artificial_options, artificial_explicit = normalize_options(_question(qid='Paper1A-Q011', canonical_id='canon-11', subtopics=['C.1'], options=[]))
            check('IBP-04: explicit options normalize with visible labels', explicit and explicit_options[0]['text'] == 'A. 1 Ω')
            check('IBP-05: missing options produce artificial A/B/C/D', not artificial_explicit and [row['text'] for row in artificial_options] == ['A', 'B', 'C', 'D'])
            roman_text = normalize_embedded_mcq_text(
                'We are given: I. Height II. Velocity III. Angle Which are needed? I and II only I and III only II and III only I, II and III'
            )
            check('IBP-05b: embedded Roman numeral lists and choices are split onto lines', all(token in roman_text for token in ['\nI. Height', '\nII. Velocity', '\nIII. Angle', '\nI and II only', '\nI, II and III']))
            body_text, extracted = extract_embedded_choice_options(
                'What is the distance traveled? $100$ m $125$ m $175$ m $250$ m'
            )
            check('IBP-05c: trailing math answer choices are extracted from problem body', body_text == 'What is the distance traveled?' and [row['text'] for row in extracted] == ['A. $100$ m', 'B. $125$ m', 'C. $175$ m', 'D. $250$ m'])
            table_body, table_options = extract_embedded_choice_options(
                'What is correct?\n | Column 1 | Column 2\nA. | ΔT | 2ΔU\nB. | 2ΔT | 2ΔU\nC. | ΔT | ΔU\nD. | 2ΔT | ΔU'
            )
            check('IBP-05d: labelled table answer rows are extracted from problem body', table_body.endswith('| Column 1 | Column 2') and table_options[0]['text'] == 'A. | ΔT | 2ΔU')
            roman_body, roman_options = extract_embedded_choice_options(roman_text)
            check('IBP-05e: Roman answer choices are extracted from problem body', 'I and II only' not in roman_body and roman_options[-1]['text'] == 'D. I, II and III')
            numeric_body, numeric_options = extract_embedded_choice_options('A temperature of 58 $^{o}$ C is equal to: -215 K 215 K -331 K 331 K')
            check('IBP-05f: trailing signed numeric answer choices are extracted from problem body', numeric_body.endswith('equal to:') and numeric_options[0]['text'] == 'A. -215 K')
            sentence_body, sentence_options = extract_embedded_choice_options('When a battery is discharging, it converts: electrical energy to potential energy. potential energy to electrical energy. electrical energy to chemical energy. chemical energy to electrical energy.')
            check('IBP-05g: trailing sentence answer choices are extracted from problem body', sentence_body.endswith('converts:') and sentence_options[-1]['text'] == 'D. chemical energy to electrical energy.')

            symbol_plan = _build_plan(source_root, static_root, _filters(subtopics=('C.1',), count=1))
            symbol_text = symbol_plan['selected'][0]['text']
            check('IBP-06: formula and symbol text is preserved', all(token in symbol_text for token in ['λ', 'θ', 'Δ', 'Ω', 'μ', '×10']))

            diff_plan = _build_plan(source_root, static_root, _filters(subtopics=('C.1', 'C.2'), count=1, difficulty=3))
            check('IBP-07: exact difficulty filter works', diff_plan['selected'][0]['canonical_id'] == 'canon-2')
            level_plan = _build_plan(source_root, static_root, _filters(subtopics=('C.1', 'C.2'), count=1, level='HL', difficulty=3))
            check('IBP-08: level filter uses source level or available_for', level_plan['selected'][0]['canonical_id'] == 'canon-2')

            seed_plan_a = _build_plan(source_root, static_root, _filters(subtopics=('C.1', 'C.2'), count=2, seed=7))
            seed_plan_b = _build_plan(source_root, static_root, _filters(subtopics=('C.1', 'C.2'), count=2, seed=7))
            check('IBP-09: deterministic seed selection works', [r['canonical_id'] for r in seed_plan_a['selected']] == [r['canonical_id'] for r in seed_plan_b['selected']])
            quota_plan = _build_plan(source_root, static_root, _filters(subtopics=('C.1', 'C.2'), count=2, per_subtopic_count=1, seed=8))
            check('IBP-09b: per-subtopic selection picks the requested count from each subtopic', [row['matched_subtopic'] for row in quota_plan['selected']] == ['C.1', 'C.2'])

            existing_topic = Topic(name='Existing', subject='IB Physics')
            db.session.add(existing_topic)
            db.session.flush()
            existing_problem = Problem(
                topic_id=existing_topic.id,
                title='Existing',
                prompt_text='Existing',
                answer_text='A',
                answer_type=PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
                difficulty=1,
            )
            db.session.add(existing_problem)
            db.session.flush()
            db.session.add(ProblemSourceMetadata(
                problem_id=existing_problem.id,
                source_system='ib_physics_question_system',
                canonical_id='canon-1',
                import_batch_id='existing',
            ))
            db.session.commit()

            duplicate_plan = _build_plan(source_root, static_root, _filters(subtopics=('C.1', 'C.2'), count=2))
            check('IBP-10: duplicate exclusion uses ProblemSourceMetadata', 'canon-1' not in {r['canonical_id'] for r in duplicate_plan['selected']})

            before_counts = (Problem.query.count(), ProblemSet.query.count(), ProblemChoiceOption.query.count())
            dry_plan = _build_plan(source_root, static_root, _filters(subtopics=('C.2',), count=1, difficulty=3))
            after_counts = (Problem.query.count(), ProblemSet.query.count(), ProblemChoiceOption.query.count())
            check('IBP-11: dry-run planning creates no database rows', before_counts == after_counts and dry_plan['selected'][0]['canonical_id'] == 'canon-2')

            write_plan = _build_plan(source_root, static_root, _filters(subtopics=('C.2',), count=1, difficulty=4))
            result = write_import_plan(write_plan)
            imported_set = db.session.get(ProblemSet, result['problem_set_id'])
            imported_problem = db.session.get(Problem, result['problem_ids'][0])
            options = sorted(imported_problem.choice_options, key=lambda row: row.position)
            blocks = sorted(imported_problem.blocks, key=lambda row: row.position)
            metadata = ProblemSourceMetadata.query.filter_by(problem_id=imported_problem.id).first()

            check('IBP-12: write mode creates ProblemSet and Problem', imported_set is not None and imported_problem is not None)
            check('IBP-13: ProblemSet defaults to Classic and Boss Rush attack', imported_set.usable_in_classic and imported_set.usable_in_boss_rush and not imported_set.usable_as_recovery and not imported_set.usable_in_team)
            check('IBP-14: write mode creates MCQ options and correct answer', len(options) == 4 and [row.is_correct for row in options] == [False, True, False, False])
            check('IBP-15: write mode copies image and stores static-relative image block', any(block.block_type == PROBLEM_BLOCK_TYPE_IMAGE for block in blocks) and Path(static_tmp, blocks[1].image_path).exists())
            check('IBP-16: markscheme is not stored in player-visible fields', 'markscheme' not in (imported_problem.prompt_text or '').lower() and 'markscheme' not in (imported_problem.answer_text or '').lower())
            check('IBP-17: metadata model records imported canonical id', metadata is not None and metadata.canonical_id == 'canon-3')
            check('IBP-18: rich text block is created before image block', blocks[0].block_type == PROBLEM_BLOCK_TYPE_RICH_TEXT and blocks[1].block_type == PROBLEM_BLOCK_TYPE_IMAGE)


if __name__ == '__main__':
    print('\nIB Physics MCQ Importer - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL IB PHYSICS IMPORTER TESTS PASSED.')
    else:
        print('SOME IB PHYSICS IMPORTER TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
