"""Validated, repeatable import of Questionbank v4 MCQs into canonical problems."""

from collections import Counter
from hashlib import sha256
import json
import os
import re
from threading import Lock
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from bs4 import BeautifulSoup, NavigableString
from flask import current_app

from app.extensions import db
from app.models.media import UploadedAsset
from app.models.problems import (
    Problem, ProblemBlock, ProblemChoiceOption, ProblemSourceMetadata, Topic,
    PROBLEM_BLOCK_TYPE_IMAGE, PROBLEM_BLOCK_TYPE_RICH_TEXT,
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
)
from app.models.subjects import Subject
from app.services.problem_content import sync_problem_legacy_compat_fields
from app.services.uploaded_media import validate_image, write_image, remove_image


SOURCE_SYSTEM = 'ib_physics_questionbank_v4'
_ID = re.compile(r'^phys_[a-f0-9]{32}$')
_ANSWER = re.compile(r'\bAnswer\s*:\s*([A-D])\b', re.I)
_LEADING_ANSWER = re.compile(r'^\s*([A-D])\b', re.I)
_IMPORT_LOCK = Lock()


class ArchiveError(ValueError):
    pass


def stage_directory():
    path = os.path.join(current_app.config['MEDIA_ROOT'], 'staging')
    os.makedirs(path, exist_ok=True)
    return path


def stage_path(stage_id):
    if not re.fullmatch(r'[a-f0-9]{32}', stage_id or ''):
        raise ArchiveError('Invalid import stage.')
    return os.path.join(stage_directory(), stage_id + '.zip')


def _archive_members(archive):
    infos = archive.infolist()
    if len(infos) > current_app.config['IMPORT_MAX_FILES']:
        raise ArchiveError('ZIP contains too many files.')
    total = 0
    names = set()
    files = {}
    for info in infos:
        name = info.filename
        if name.startswith(('/', '\\')) or '\\' in name or ':' in name or any(part in ('', '.', '..') for part in name.rstrip('/').split('/')):
            raise ArchiveError(f'Unsafe archive path: {name[:100]}')
        if name in names:
            raise ArchiveError(f'Duplicate archive entry: {name[:100]}')
        names.add(name)
        if info.is_dir():
            continue
        total += info.file_size
        if total > current_app.config['IMPORT_MAX_EXPANDED_BYTES'] or info.file_size > 16 * 1024 * 1024:
            raise ArchiveError('ZIP expands beyond the configured size limit.')
        if info.compress_size and info.file_size / info.compress_size > 250:
            raise ArchiveError('ZIP entry has an unreasonable compression ratio.')
        if not (name.endswith('.json') or name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')) or name.endswith('/.gitkeep')):
            raise ArchiveError(f'Unexpected file type in ZIP: {name[:100]}')
        files[name] = info
    # Accept either files at the root or inside one exported questionbank folder.
    roots = {name.split('/')[0] for name in files}
    prefix = ''
    if 'problems' not in roots:
        if len(roots) != 1:
            raise ArchiveError('ZIP must contain problems/ and assets/ folders.')
        prefix = next(iter(roots)) + '/'
    problem_names = sorted(name for name in files if name.startswith(prefix + 'problems/') and name.endswith('.json'))
    if not problem_names:
        raise ArchiveError('No v4 problem JSON records found.')
    for name in files:
        relative = name[len(prefix):] if name.startswith(prefix) else name
        if not (relative.startswith('problems/') and relative.endswith('.json') or
                relative.startswith('assets/') and relative.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')) or
                relative.endswith('/.gitkeep')):
            raise ArchiveError(f'Unexpected file outside v4 problems/assets: {name[:100]}')
    return files, prefix, problem_names


def _parse_record(raw, archive, files, prefix):
    if not isinstance(raw, dict) or raw.get('schema_version') != 'question.v4':
        raise ValueError('Not a Questionbank v4 record.')
    source_id = raw.get('id')
    if not isinstance(source_id, str) or not _ID.fullmatch(source_id):
        raise ValueError('Missing or invalid phys_ source ID.')
    if raw.get('type') != 'mcq':
        raise ValueError('Unsupported answer type (only v4 MCQ is supported).')
    if (raw.get('review') or {}).get('status') not in (None, 'approved'):
        raise ValueError('Question has not been approved in v4.')
    question_html = (raw.get('question') or {}).get('html')
    markscheme_html = (raw.get('markscheme') or {}).get('html')
    if not isinstance(question_html, str) or not isinstance(markscheme_html, str):
        raise ValueError('Question or markscheme HTML is missing.')
    soup = BeautifulSoup(question_html, 'html.parser')
    if soup.find(['script', 'style', 'iframe', 'object', 'embed', 'form']):
        raise ValueError('Question contains unsupported active HTML.')
    for math_span in soup.select('[data-latex]'):
        latex = math_span.get('data-latex')
        if not isinstance(latex, str) or len(latex) > 2000:
            raise ValueError('Malformed math expression.')
        math_span.replace_with(NavigableString(f'${latex}$'))
    option_nodes = soup.select('li[data-label], tr[data-label]')
    labels = [str(node.get('data-label', '')).upper() for node in option_nodes]
    if labels != ['A', 'B', 'C', 'D']:
        raise ValueError('Expected exactly four ordered A–D options.')
    options = []
    option_image_refs = []
    for node in option_nodes:
        images = node.find_all('img')
        if len(images) > 1:
            raise ValueError('An option contains multiple images.')
        image_ref = None
        if images:
            src = images[0].get('src', '')
            if not src.startswith('asset:'):
                raise ValueError(f'Unresolved option image: {src[:80]}')
            image_ref = src[6:]
            images[0].decompose()
        option_text = node.get_text(' ', strip=True)
        option_text = re.sub(r'^[A-D][.\s)]+', '', option_text).strip()
        if not option_text and image_ref:
            option_text = f'Option {node.get("data-label", "").upper()}'
        if not option_text or len(option_text) > 512:
            raise ValueError('An option is empty or exceeds the database limit.')
        options.append(option_text)
        option_image_refs.append(image_ref)
        node.decompose()
    answer_text = BeautifulSoup(markscheme_html, 'html.parser').get_text(' ', strip=True)
    match = _ANSWER.search(answer_text) or _LEADING_ANSWER.search(answer_text)
    if not match:
        raise ValueError('Could not determine one correct A–D answer.')
    correct_label = match.group(1).upper()
    listed_assets = raw.get('assets') or []
    if not isinstance(listed_assets, list):
        raise ValueError('Asset list is malformed.')
    assets = {}
    for spec in listed_assets:
        if not isinstance(spec, dict) or not isinstance(spec.get('id'), str) or not isinstance(spec.get('file'), str):
            raise ValueError('Asset metadata is malformed.')
        path = spec['file']
        if not re.fullmatch(r'assets/[a-f0-9]{64}\.(?:png|jpg|jpeg|webp)', path):
            raise ValueError('Asset path is invalid.')
        member = prefix + path
        if member not in files:
            raise ValueError(f'Missing asset: {path}')
        image_bytes = archive.read(member)
        expected_hash = spec.get('sha256')
        if expected_hash and sha256(image_bytes).hexdigest() != expected_hash:
            raise ValueError(f'Asset checksum mismatch: {path}')
        validate_image(image_bytes)
        if spec['id'] in assets:
            raise ValueError('Duplicate asset ID in question.')
        assets[spec['id']] = (path, image_bytes)
    for image_ref in option_image_refs:
        if image_ref and image_ref not in assets:
            raise ValueError(f'Unresolved option image: {image_ref[:80]}')
    image_refs = []
    for image in soup.find_all('img'):
        src = image.get('src', '')
        if not src.startswith('asset:') or src[6:] not in assets:
            raise ValueError(f'Unresolved question image: {src[:80]}')
        image_refs.append(src[6:])
        image.decompose()
    for figure in soup.find_all('figure'):
        figure.decompose()
    body = soup.get_text('\n', strip=True)
    if not body:
        raise ValueError('Question text is empty.')
    raw_difficulty = raw.get('difficulty')
    difficulty = max(1, min(5, raw_difficulty)) if isinstance(raw_difficulty, int) else 1
    classes = raw.get('classes') or []
    class_code = str(classes[0])[:32] if isinstance(classes, list) and classes else 'Unclassified'
    source_hash = sha256(json.dumps({k: raw.get(k) for k in ('question', 'markscheme', 'assets', 'classes', 'difficulty', 'type')}, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    return {'id': source_id, 'body': body, 'options': options, 'correct': correct_label,
            'assets': assets, 'image_refs': image_refs, 'option_image_refs': option_image_refs, 'class_code': class_code,
            'difficulty': difficulty, 'hash': source_hash,
            'answer_hash': sha256((correct_label + '\0' + '\0'.join(options)).encode('utf-8')).hexdigest(),
            'metadata': {'paper': raw.get('paper'), 'level': raw.get('level'), 'classes': classes}}


def inspect_archive(path):
    try:
        with ZipFile(path) as archive:
            files, prefix, names = _archive_members(archive)
            existing = {row.canonical_id: row for row in ProblemSourceMetadata.query.filter_by(source_system=SOURCE_SYSTEM).all()}
            parsed = []
            errors = []
            ids = []
            for name in names:
                try:
                    raw = json.loads(archive.read(name).decode('utf-8'))
                    ids.append(raw.get('id') if isinstance(raw, dict) else None)
                    parsed.append((name, _parse_record(raw, archive, files, prefix)))
                except (ValueError, UnicodeDecodeError, TypeError) as exc:
                    message = str(exc)
                    errors.append({'file': name, 'error': message})
            duplicates = {key for key, count in Counter(ids).items() if key and count > 1}
            valid = []
            for name, row in parsed:
                if row['id'] in duplicates:
                    errors.append({'file': name, 'error': 'Duplicate source ID in ZIP.'})
                else:
                    old = existing.get(row['id'])
                    row['action'] = 'new' if old is None else ('skip' if old.content_hash == row['hash'] else 'update')
                    valid.append(row)
            counts = Counter(row['action'] for row in valid)
            return {'total': len(names), 'valid': len(valid), 'new': counts['new'],
                    'matching': sum(row['id'] in existing for row in valid), 'update': counts['update'],
                    'skip': counts['skip'], 'invalid': len(errors),
                    'missing_assets': sum('Missing asset:' in e['error'] for e in errors),
                    'duplicate_source_ids': len(duplicates),
                    'unsupported_answer_types': sum('Unsupported answer type' in e['error'] for e in errors),
                    'errors': sorted(errors, key=lambda item: 'Unsupported answer type' in item['error'])[:30], 'records': valid}
    except (BadZipFile, OSError, RuntimeError) as exc:
        raise ArchiveError('File is not a readable Questionbank v4 ZIP.') from exc


def apply_import(path, subject_name):
    """Revalidate and apply all valid rows in one DB transaction; clean new files on failure."""
    with _IMPORT_LOCK:
        plan = inspect_archive(path)
        created_files = []
        batch_id = uuid4().hex
        try:
            subject = Subject.query.filter_by(name=subject_name).first()
            if subject is None:
                subject = Subject(name=subject_name)
                db.session.add(subject)
                db.session.flush()
            topic_cache = {}
            asset_cache = {}
            applied = Counter()
            for row in plan['records']:
                if row['action'] == 'skip':
                    applied['skip'] += 1
                    continue
                topic_name = f'IB Physics {row["class_code"]}'
                topic = topic_cache.get(topic_name) or Topic.query.filter_by(name=topic_name).first()
                if topic is None:
                    topic = Topic(name=topic_name, subject_id=subject.id, subject=subject.name)
                    db.session.add(topic)
                    db.session.flush()
                elif topic.subject_id != subject.id:
                    raise ValueError(f'Topic {topic_name} belongs to another Subject.')
                topic_cache[topic_name] = topic
                metadata = ProblemSourceMetadata.query.filter_by(source_system=SOURCE_SYSTEM, canonical_id=row['id']).first()
                if metadata:
                    problem = metadata.problem
                    problem.blocks.clear()
                    problem.choice_options.clear()
                    problem.accepted_answers.clear()
                    db.session.flush()
                else:
                    problem = Problem(topic_id=topic.id, title=row['id'], prompt_text='', answer_text='')
                    db.session.add(problem)
                    db.session.flush()
                    metadata = ProblemSourceMetadata(problem_id=problem.id, source_system=SOURCE_SYSTEM,
                                                     canonical_id=row['id'], source_id=row['id'], import_batch_id=batch_id)
                    db.session.add(metadata)
                problem.topic_id = topic.id
                problem.title = f'IB Physics {row["class_code"]} · {row["id"][-8:]}'
                problem.answer_type = PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE
                problem.difficulty = row['difficulty']
                problem.blocks.append(ProblemBlock(position=1, block_type=PROBLEM_BLOCK_TYPE_RICH_TEXT, text_content=row['body']))
                def imported_asset(asset_id):
                    source_path, image_bytes = row['assets'][asset_id]
                    source_sha = sha256(image_bytes).hexdigest()
                    asset = asset_cache.get(source_sha) or UploadedAsset.query.filter_by(category='problem_image', asset_key=source_sha).first()
                    if asset is None:
                        saved = write_image(image_bytes)
                        created_files.append(saved['storage_name'])
                        asset = UploadedAsset(category='problem_image', display_name=source_path.rsplit('/', 1)[-1],
                                              asset_key=source_sha, **{k: saved[k] for k in ('storage_name', 'media_type', 'sha256')})
                        db.session.add(asset)
                        db.session.flush()
                    asset_cache[source_sha] = asset
                    return asset
                for index, asset_id in enumerate(row['image_refs'], start=2):
                    asset = imported_asset(asset_id)
                    problem.blocks.append(ProblemBlock(position=index, block_type=PROBLEM_BLOCK_TYPE_IMAGE,
                                                       image_path=f'uploaded:{asset.id}', image_width_pct=100))
                for index, option_text in enumerate(row['options']):
                    image_ref = row['option_image_refs'][index]
                    image_asset = imported_asset(image_ref) if image_ref else None
                    problem.choice_options.append(ProblemChoiceOption(position=index + 1, option_text=option_text,
                                                                      image_asset_id=image_asset.id if image_asset else None,
                                                                      is_correct='ABCD'[index] == row['correct']))
                db.session.flush()
                sync_problem_legacy_compat_fields(problem)
                metadata.content_hash = row['hash']
                metadata.answer_hash = row['answer_hash']
                metadata.raw_metadata_json = row['metadata']
                metadata.import_batch_id = batch_id
                applied[row['action']] += 1
            db.session.commit()
            return {**{key: plan[key] for key in ('total', 'valid', 'invalid', 'missing_assets', 'duplicate_source_ids', 'unsupported_answer_types', 'errors')},
                    'new': applied['new'], 'update': applied['update'], 'skip': applied['skip']}
        except Exception:
            db.session.rollback()
            for filename in created_files:
                remove_image(filename)
            raise
