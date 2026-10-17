"""Authoring, persistence and renderer integration checks using isolated storage."""
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app import create_app
from app.extensions import db
from app.models.gear import GearItemDefinition
from app.models.media import UploadedAsset
from app.models.player import Player
from app.services.avatar import build_player_avatar_view, list_available_face_keys
from app.services.gear import is_item_variant_compatible_for_player, resolve_gear_icon_static_path
from app.services import gear_studio
from config import Config


def png(color=(220, 40, 70, 255), size=(24, 36)):
    output = BytesIO()
    Image.new('RGBA', size, color).save(output, format='PNG')
    return output.getvalue()


@pytest.fixture
def studio(tmp_path):
    class TestConfig(Config):
        GAME_ENV = 'development'
        TESTING = True
        SECRET_KEY = 'studio-test-only'
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + (tmp_path / 'test.sqlite').as_posix()
        INSTANCE_PATH = str(tmp_path / 'instance')
        MEDIA_ROOT = str(tmp_path / 'media')
        WTF_CSRF_ENABLED = False
        SHARED_IDENTITY_URL = ''
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        for username, admin in [('studio-admin', True), ('studio-player', False)]:
            user = Player(username=username, is_admin=admin)
            user.set_password('test-password-12345')
            db.session.add(user)
        db.session.commit()
        client = app.test_client()
        client.post('/login', data=dict(username='studio-admin', password='test-password-12345'))
        yield app, client, tmp_path
        db.session.remove()


def save(client, **overrides):
    pixels = overrides.pop('pixels', png())
    data = dict(slot='face', target='new', variant='m', layer='front', name='Test artwork', price=5,
                revision='', transform=dict(x=100, y=200, width=120, rotation=0)) | overrides
    return client.post('/admin/gear-studio/save', data={'metadata': json.dumps(data),
                       'image': (BytesIO(pixels), 'source.png')}, content_type='multipart/form-data')


@pytest.mark.parametrize('slot', list(gear_studio.SLOTS))
def test_save_exports_only_the_imported_layer_and_registers_it(studio, slot):
    app, client, tmp = studio
    response = save(client, slot=slot)
    assert response.status_code == 200, response.json
    result = response.json
    asset = db.session.get(UploadedAsset, result['asset_id'])
    with Image.open(tmp / 'media' / asset.storage_name) as image:
        assert image.size == (1100, 1200)
        assert image.mode == 'RGBA'
        assert image.getchannel('A').getbbox() == (100, 200, 220, 380)
        assert image.getpixel((600, 600))[3] == 0  # no body/reference art baked in
    assert (tmp / 'media' / asset.editor_state['source_name']).is_file()
    if slot == 'face':
        assert asset.asset_key in list_available_face_keys('m')
        assert asset.asset_key not in list_available_face_keys('f')
        item_id = None
    else:
        item = db.session.get(GearItemDefinition, result['target'])
        assert item.is_active and item.is_blacksmith_visible and item.diamond_cost == 5
        assert is_item_variant_compatible_for_player(item, 'm')
        assert not is_item_variant_compatible_for_player(item, 'f')
        with app.test_request_context():
            assert resolve_gear_icon_static_path(item_id=item.id, slot_type=slot).startswith('/media/')
        item_id = item.id
    loadout = SimpleNamespace(**{key + '_item_id': item_id if key == slot else None
                                 for key in gear_studio.SLOTS if key != 'face'})
    player = SimpleNamespace(avatar_body_variant='m', selected_face_key=asset.asset_key if slot == 'face' else '001')
    with app.test_request_context():
        view = build_player_avatar_view(player, loadout)
    label = gear_studio.LAYER_NAMES[slot]['front']
    assert view['layer_map'][label]['static_path'] == f'/media/{asset.id}'


def test_reopen_replace_and_other_body_preserve_catalog_settings(studio):
    _app, client, tmp = studio
    first = save(client, slot='head').json
    item = db.session.get(GearItemDefinition, first['target'])
    item.mine_gold_delta = 12
    item.diamond_cost = 22
    db.session.commit()
    asset = db.session.get(UploadedAsset, first['asset_id'])
    old_files = {asset.storage_name, asset.editor_state['source_name']}
    editor = client.get('/admin/gear-studio/editor', query_string=dict(slot='head', target=item.id, variant='m', layer='front')).json
    assert editor['transform'] == dict(x=100, y=200, width=120, rotation=0)
    assert client.get(editor['source_url']).status_code == 200
    second = save(client, slot='head', target=item.id, revision=first['revision'],
                  transform=dict(x=300, y=250, width=180, rotation=20))
    assert second.status_code == 200
    assert second.json['asset_id'] == first['asset_id']
    assert all(not (tmp / 'media' / name).exists() for name in old_files)
    assert (item.mine_gold_delta, item.diamond_cost) == (12, 22)
    assert save(client, slot='head', target=item.id, revision=first['revision']).status_code == 409
    third = save(client, slot='head', target=item.id, variant='f')
    assert third.status_code == 200
    assert is_item_variant_compatible_for_player(item, 'f')
    assert db.session.get(UploadedAsset, first['asset_id']).variant == 'm'


def test_catalog_uses_actual_game_layers_and_existing_assets(studio):
    _app, client, _tmp = studio
    result = save(client, slot='chest').json
    response = client.get('/admin/gear-studio/catalog')
    assert response.status_code == 200
    data = response.json
    assert 'body-upper' in data['base']['m'] and 'body-lower' in data['base']['f']
    item = next(item for item in data['items'] if item['id'] == result['target'])
    assert item['layers']['m']['chest'].startswith('/media/')
    assert item['layers']['f'] == {}
    assert data['order'].index('face') < data['order'].index('head-front')
    assert client.get('/admin/gear-studio/').status_code == 200


@pytest.mark.parametrize('change', [
    dict(pixels=b'bad png'), dict(pixels=png((0, 0, 0, 0))),
    dict(transform=dict(x=99999, y=0, width=100, rotation=0)),
    dict(transform=dict(x=0, y=0, width=float('nan'), rotation=0)),
    dict(transform=dict(x=4000, y=4000, width=10, rotation=0)),
    dict(slot='pocket'), dict(variant='shared'), dict(layer='back'), dict(name=''), dict(target='missing'),
])
def test_bad_input_leaves_no_rows_or_files(studio, change):
    _app, client, tmp = studio
    assert save(client, **change).status_code == 400
    assert UploadedAsset.query.count() == 0 and GearItemDefinition.query.count() == 0
    assert not list((tmp / 'media').glob('*'))


def test_commit_failure_removes_new_images(studio, monkeypatch):
    _app, _client, tmp = studio
    def fail():
        raise RuntimeError('simulated commit failure')
    monkeypatch.setattr(db.session, 'commit', fail)
    with pytest.raises(RuntimeError):
        gear_studio.save_element(dict(slot='face', variant='m', target='new', layer='front', name='Rollback',
            revision='', transform=dict(x=100, y=200, width=100, rotation=0)), png())
    assert UploadedAsset.query.count() == 0
    assert not list((tmp / 'media').glob('*'))


def test_asset_replace_and_delete_remove_editable_sources(studio):
    _app, client, tmp = studio
    result = save(client).json
    asset = db.session.get(UploadedAsset, result['asset_id'])
    old_source = asset.editor_state['source_name']
    client.post(f'/admin/assets/{asset.id}/replace', data={'image': (BytesIO(png()), 'new.png')},
                content_type='multipart/form-data')
    assert db.session.get(UploadedAsset, asset.id).editor_state is None
    assert not (tmp / 'media' / old_source).exists()
    client.post(f'/admin/assets/{asset.id}/delete')
    assert UploadedAsset.query.count() == 0
    assert not list((tmp / 'media').glob('*'))


def test_delete_studio_gear_cleans_all_images(studio):
    _app, client, tmp = studio
    result = save(client, slot='head').json
    client.post('/admin/gear/' + result['target'] + '/delete')
    assert UploadedAsset.query.count() == 0
    assert GearItemDefinition.query.count() == 0
    assert not list((tmp / 'media').glob('*'))


def test_admin_access_and_csrf(studio):
    app, client, _tmp = studio
    client.get('/logout')
    client.post('/login', data=dict(username='studio-player', password='test-password-12345'))
    assert client.get('/admin/gear-studio/').status_code == 403
    assert client.get('/admin/gear-studio/catalog').status_code == 403
    assert save(client).status_code == 403
    client.get('/logout')
    client.post('/login', data=dict(username='studio-admin', password='test-password-12345'))
    app.config['WTF_CSRF_ENABLED'] = True
    assert save(client).status_code == 400
