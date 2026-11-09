"""Freeze the content and local image bytes used by learning reports."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

from flask import current_app, has_request_context

from app.extensions import db
from app.models.media import UploadedAsset
from app.services.problem_content import build_problem_body_view, build_problem_choice_view

ASSET_NAME = re.compile(r'^[a-f0-9]{64}\.(png|jpg|jpeg|webp)$')


def asset_directory():
    return Path(current_app.config['MEDIA_ROOT']) / 'learning-assets'


def question_in_unfinished_round(problem_id):
    from app.models.analytics import AnalyticsRoundProblem
    from app.models.game import GameRound
    return db.session.query(AnalyticsRoundProblem.id).join(
        GameRound, GameRound.id == AnalyticsRoundProblem.round_id).filter(
            AnalyticsRoundProblem.problem_id == problem_id, GameRound.ended_at.is_(None)).first() is not None


def _freeze_image(reference):
    if not reference:
        return None
    if reference.startswith('uploaded:'):
        try:
            asset = db.session.get(UploadedAsset, int(reference.split(':', 1)[1]))
        except ValueError:
            return None
        if not asset:
            return None
        root = Path(current_app.config['MEDIA_ROOT']).resolve()
        path = (root / asset.storage_name).resolve()
    else:
        root = Path(current_app.static_folder).resolve()
        path = (root / reference).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    suffix = path.suffix.lower()
    if suffix not in ('.png', '.jpg', '.jpeg', '.webp') or path.stat().st_size > 16 * 1024 * 1024:
        return None
    data = path.read_bytes()
    name = sha256(data).hexdigest() + suffix
    folder = asset_directory()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with (folder / name).open('xb') as handle:
            handle.write(data)
    except FileExistsError:
        pass
    return name


def freeze_question(problem):
    if not has_request_context():
        with current_app.test_request_context():
            return freeze_question(problem)
    body = deepcopy(build_problem_body_view(problem))
    choices = deepcopy(build_problem_choice_view(problem))
    warnings = []
    for block in body['blocks']:
        if block['type'] == 'image':
            block['asset_name'] = _freeze_image(block.get('image_path'))
            block.pop('image_url', None)
            block.pop('image_path', None)
            if not block['asset_name']:
                warnings.append('A question image could not be frozen.')
    by_id = {option.id: option for option in problem.choice_options}
    for option in choices['options']:
        source = by_id[option['id']]
        option.pop('rendered_html', None)
        option['label'] = chr(64 + source.position) if 1 <= source.position <= 26 else str(source.position)
        option['asset_name'] = _freeze_image(f'uploaded:{source.image_asset_id}') if source.image_asset_id else None
        if source.image_asset_id and not option['asset_name']:
            warnings.append('An option image could not be frozen.')
    metadata = getattr(problem, 'source_metadata', None)
    raw = metadata.raw_metadata_json or {} if metadata else {}
    key = {
        'correct_option_ids': [o.id for o in problem.choice_options if o.is_correct],
        'accepted_answers': [a.answer_text for a in problem.accepted_answers] or ([problem.answer_text] if problem.answer_type != 'multiple_choice' else []),
    }
    result = {
        'schema_version': 'question_snapshot.v1', 'title': problem.title,
        'answer_type': problem.answer_type, 'body': body, 'choices': choices,
        'answer_key': key, 'explanation': raw.get('explanation_text'),
        'difficulty': problem.difficulty, 'difficulty_is_calibrated': False,
        'source_system': metadata.source_system if metadata else None,
        'canonical_id': metadata.canonical_id if metadata else None,
        'classification': {k: raw.get(k) for k in ('paper', 'level', 'classes')},
        'warnings': warnings,
    }
    result['version_hash'] = sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


def snapshot_assets(content):
    content = content or {}
    return sorted({item['asset_name'] for item in content.get('body', {}).get('blocks', []) + content.get('choices', {}).get('options', [])
                   if item.get('asset_name') and ASSET_NAME.fullmatch(item['asset_name'])})
