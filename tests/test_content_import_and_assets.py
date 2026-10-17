"""Focused integration checks for the new admin import and persistent media paths."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from PIL import Image

from app import create_app
from app.extensions import db
from app.models.gear import GearItemDefinition
from app.models.media import UploadedAsset
from app.models.player import Player
from app.models.problems import Problem, ProblemSet
from app.services.avatar import build_player_avatar_view, list_available_face_keys
from app.services.problem_content import build_problem_body_view, build_problem_choice_view, check_problem_multiple_choice_answer
from app.services.v4_import import ArchiveError, apply_import, inspect_archive
from config import Config


SOURCE_ID = 'phys_0123456789abcdef0123456789abcdef'


def image_bytes(kind='PNG'):
    out = BytesIO()
    Image.new('RGB', (6, 6), (255, 30, 10)).save(out, format=kind)
    return out.getvalue()


def record(*, question='What is 2 + 2?', image=False, kind='mcq'):
    body = f'<p>{question}</p>'
    assets = []
    if image:
        from hashlib import sha256
        data = image_bytes()
        digest = sha256(data).hexdigest()
        body += '<figure><img src="asset:fig_01"/></figure>'
        assets = [{'id': 'fig_01', 'file': f'assets/{digest}.png', 'sha256': digest}]
    body += '<ol class="mcq-options"><li data-label="A">3</li><li data-label="B">4</li><li data-label="C">5</li><li data-label="D">6</li></ol>'
    return {'schema_version': 'question.v4', 'id': SOURCE_ID, 'type': kind,
            'question': {'html': body}, 'markscheme': {'html': '<p><strong>Answer:</strong> B</p>'},
            'assets': assets, 'classes': ['C.2'], 'difficulty': 2, 'review': {'status': 'approved'}}


def archive_bytes(records, *, asset=True, extra=None):
    import json
    out = BytesIO()
    with ZipFile(out, 'w') as zipped:
        for index, row in enumerate(records):
            zipped.writestr(f'problems/{index}.json', json.dumps(row))
            if asset:
                for spec in row.get('assets', []):
                    zipped.writestr(spec['file'], image_bytes())
        if extra:
            zipped.writestr(*extra)
    return out.getvalue()


@pytest.fixture
def ctx(tmp_path):
    class TestConfig(Config):
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + (tmp_path / 'test.db').as_posix()
        TESTING = True
        WTF_CSRF_ENABLED = False
        MEDIA_ROOT = str(tmp_path / 'media')
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        admin = Player(username='asset_admin', is_admin=True)
        admin.set_password('test-password-12345')
        player = Player(username='asset_player', is_admin=False)
        player.set_password('test-password-12345')
        db.session.add_all([admin, player])
        db.session.add(GearItemDefinition(id='test_head', slot_type='head', name='Test head', description=''))
        db.session.commit()
        yield app, tmp_path
        db.session.remove()


def login(client, username='asset_admin'):
    return client.post('/login', data={'username': username, 'password': 'test-password-12345'})


def test_mcq_import_repeat_update_and_shared_rendering(ctx):
    app, tmp = ctx
    path = tmp / 'bank.zip'
    path.write_bytes(archive_bytes([record(image=True)]))
    preview = inspect_archive(path)
    assert (preview['valid'], preview['new'], preview['missing_assets']) == (1, 1, 0)
    result = apply_import(path, 'Physics')
    assert result['new'] == 1 and UploadedAsset.query.count() == 1
    problem = Problem.query.one()
    original_id = problem.id
    assert len(problem.choice_options) == 4
    assert sum(option.is_correct for option in problem.choice_options) == 1
    assert [option.option_text for option in problem.choice_options] == ['3', '4', '5', '6']
    assert check_problem_multiple_choice_answer(problem, problem.choice_options[1].id)
    assert not check_problem_multiple_choice_answer(problem, problem.choice_options[0].id)
    problem_set = ProblemSet(name='Test set')
    problem_set.problems.append(problem)
    db.session.add(problem_set)
    db.session.commit()
    with app.test_request_context():
        body = build_problem_body_view(problem)
        assert body['blocks'][1]['image_url'].startswith('/media/')
    client = app.test_client()
    login(client)
    assert client.get('/admin/problems').status_code == 200
    assert client.get(f'/admin/problems/{problem.id}/content').status_code == 200
    assert inspect_archive(path)['skip'] == 1
    assert apply_import(path, 'Physics')['skip'] == 1
    changed = record(question='What is two plus two?', image=True)
    path.write_bytes(archive_bytes([changed]))
    assert inspect_archive(path)['update'] == 1
    assert apply_import(path, 'Physics')['update'] == 1
    db.session.refresh(problem)
    assert problem.id == original_id and problem_set.problems.count() == 1
    assert 'two plus two' in problem.blocks[0].text_content


def test_invalid_duplicate_missing_and_untrusted_archive(ctx):
    _app, tmp = ctx
    path = tmp / 'bad.zip'
    path.write_bytes(archive_bytes([record(), record()]))
    report = inspect_archive(path)
    assert report['duplicate_source_ids'] == 1 and report['valid'] == 0
    broken = record(image=True)
    path.write_bytes(archive_bytes([broken], asset=False))
    assert inspect_archive(path)['missing_assets'] == 1
    path.write_bytes(archive_bytes([record(kind='structured')]))
    assert inspect_archive(path)['unsupported_answer_types'] == 1
    path.write_bytes(archive_bytes([{'schema_version': 'question.v4'}]))
    assert inspect_archive(path)['invalid'] == 1
    path.write_bytes(archive_bytes([record()], extra=('../evil.py', 'bad')))
    with pytest.raises(ArchiveError):
        inspect_archive(path)
    path.write_bytes(b'not a zip')
    with pytest.raises(ArchiveError):
        inspect_archive(path)
    assert Problem.query.count() == 0


def test_image_only_multiple_choice_options(ctx):
    app, tmp = ctx
    row = record(image=True)
    row['question']['html'] = '<p>Which graph?</p><ol class="mcq-options">' + ''.join(
        f'<li data-label="{letter}"><img src="asset:fig_01"></li>' for letter in 'ABCD') + '</ol>'
    path = tmp / 'image-options.zip'
    path.write_bytes(archive_bytes([row]))
    assert inspect_archive(path)['valid'] == 1
    assert apply_import(path, 'Physics')['new'] == 1
    problem = Problem.query.one()
    assert all(option.image_asset_id for option in problem.choice_options)
    with app.test_request_context():
        assert all('/media/' in option['rendered_html'] for option in build_problem_choice_view(problem)['options'])
    assert check_problem_multiple_choice_answer(problem, problem.choice_options[1].id)


def test_admin_validate_then_confirm_import(ctx):
    app, _tmp = ctx
    client = app.test_client()
    login(client)
    response = client.post('/admin/content-import/', data={'action': 'validate',
        'archive': (BytesIO(archive_bytes([record()])), 'questions.zip')},
        content_type='multipart/form-data')
    assert response.status_code == 200
    assert b'Preview changes' in response.data
    assert Problem.query.count() == 0
    with client.session_transaction() as session:
        stage_id = session['v4_import_stage']['id']
    response = client.post('/admin/content-import/', data={'action': 'import', 'stage_id': stage_id})
    assert response.status_code == 200
    assert b'Created: 1' in response.data
    assert Problem.query.count() == 1


def test_import_failure_rolls_back_database_and_new_media(ctx, monkeypatch):
    _app, tmp = ctx
    path = tmp / 'rollback.zip'
    path.write_bytes(archive_bytes([record(image=True)]))
    def fail(_problem):
        raise RuntimeError('synthetic transaction failure')
    monkeypatch.setattr('app.services.v4_import.sync_problem_legacy_compat_fields', fail)
    with pytest.raises(RuntimeError):
        apply_import(path, 'Physics')
    assert Problem.query.count() == 0 and UploadedAsset.query.count() == 0
    assert not list(Path(tmp / 'media').glob('*.png'))


@pytest.mark.parametrize('kind,extension', [('PNG', 'png'), ('JPEG', 'jpg'), ('WEBP', 'webp')])
def test_asset_upload_replace_and_persistence(ctx, kind, extension):
    app, tmp = ctx
    client = app.test_client()
    login(client)
    response = client.post('/admin/assets/', data={'display_name': 'New face', 'category': 'face_m',
        'asset_key': 'u_face_1', 'image': (BytesIO(image_bytes(kind)), 'face.' + extension)},
        content_type='multipart/form-data')
    assert response.status_code == 302
    asset = UploadedAsset.query.one()
    assert client.get(f'/media/{asset.id}').status_code == 200
    assert (tmp / 'media' / asset.storage_name).exists()
    class RestartConfig(Config):
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + (tmp / 'test.db').as_posix()
        TESTING = True
        MEDIA_ROOT = str(tmp / 'media')
    restarted_app = create_app(RestartConfig)
    with restarted_app.app_context():
        assert restarted_app.test_client().get(f'/media/{asset.id}').status_code == 200
    player = Player.query.filter_by(username='asset_player').one()
    player.selected_face_key = 'u_face_1'
    db.session.commit()
    with app.test_request_context():
        loadout = SimpleNamespace(head_item_id=None, chest_item_id=None, boots_item_id=None,
                                  main_hand_item_id=None, off_hand_item_id=None)
        assert any(layer['label'] == 'face' and layer['static_path'].startswith('/media/')
                   for layer in build_player_avatar_view(player, loadout)['layers'])
    assert '001' in list_available_face_keys('m')  # packaged face still available
    assert 'u_face_1' in list_available_face_keys('m')
    client.post(f'/admin/assets/{asset.id}/delete')
    assert UploadedAsset.query.count() == 1  # referenced face cannot be deleted silently
    old_id = asset.id
    client.post(f'/admin/assets/{asset.id}/replace', data={'image': (BytesIO(image_bytes('PNG')), 'new.png')},
                content_type='multipart/form-data')
    assert db.session.get(UploadedAsset, old_id) is not None and client.get(f'/media/{old_id}').status_code == 200
    assert (tmp / 'media' / asset.storage_name).exists()


def test_asset_rejections_gear_attachment_and_admin_guard(ctx):
    app, _tmp = ctx
    client = app.test_client()
    login(client, 'asset_player')
    assert client.get('/admin/assets/').status_code == 403
    assert client.get('/admin/content-import/').status_code == 403
    client.get('/logout')
    login(client)
    common = {'display_name': 'Head front', 'category': 'gear_layer', 'gear_item_id': 'test_head',
              'variant': 'm', 'layer': 'front'}
    client.post('/admin/assets/', data={**common, 'image': (BytesIO(b'not an image'), 'fake.png')},
                content_type='multipart/form-data')
    assert UploadedAsset.query.count() == 0
    client.post('/admin/assets/', data={**common, 'image': (BytesIO(b'<svg/>'), 'fake.svg')},
                content_type='multipart/form-data')
    assert UploadedAsset.query.count() == 0
    client.post('/admin/assets/', data={**common, 'image': (BytesIO(image_bytes()), 'front.png')},
                content_type='multipart/form-data')
    asset = UploadedAsset.query.one()
    item = db.session.get(GearItemDefinition, 'test_head')
    player = Player.query.filter_by(username='asset_player').one()
    loadout = SimpleNamespace(head_item_id=item.id, chest_item_id=None, boots_item_id=None,
                              main_hand_item_id=None, off_hand_item_id=None)
    with app.test_request_context():
        assert any(layer['label'] == 'head-front' and layer['static_path'] == f'/media/{asset.id}'
                   for layer in build_player_avatar_view(player, loadout)['layers'])
    client.post(f'/admin/assets/{asset.id}/delete')
    assert UploadedAsset.query.count() == 1
