import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.gear import GearItemDefinition, PlayerGearLoadout
from app.models.player import Player
from app.services.avatar import (
    build_player_avatar_view,
    list_available_face_keys,
    set_player_body_variant,
)
from app.services.gear import is_item_variant_compatible_for_player, resolve_gear_icon_static_path


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'avatar-variant-stabilization-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False


flask_app = create_app(_TestConfig)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n')


def _login(client, username, password='pass1234'):
    return client.post(
        '/login',
        data={'username': username, 'password': password},
        follow_redirects=True,
    )


def test_avatar_body_variant_defaults_and_layer_keys():
    with flask_app.app_context():
        db.create_all()
        player = Player(username='variant_default_player')
        player.set_password('pass1234')
        db.session.add(player)
        db.session.flush()
        loadout = PlayerGearLoadout(player_id=player.id)
        db.session.add(loadout)
        db.session.commit()

        assert player.avatar_body_variant == 'm'

        avatar = build_player_avatar_view(player, loadout)
        layer_map = avatar['layer_map']
        assert 'body-upper' in layer_map
        assert 'face' in layer_map
        assert 'off-hand-base' in layer_map
        assert ('body-lower' in layer_map) or ('boots' in layer_map)


def test_female_body_falls_back_to_m_when_f_assets_missing():
    with flask_app.app_context():
        db.create_all()
        player = Player(username='variant_fallback_player', avatar_body_variant='f')
        player.set_password('pass1234')
        db.session.add(player)
        db.session.flush()
        loadout = PlayerGearLoadout(player_id=player.id)
        db.session.add(loadout)
        db.session.commit()

        avatar = build_player_avatar_view(player, loadout)
        static_root = Path(flask_app.static_folder)
        has_f_upper = (static_root / 'avatars' / 'bodies' / 'f' / 'body_upper.png').is_file()
        has_f_lower = (static_root / 'avatars' / 'bodies' / 'f' / 'body_lower.png').is_file()
        expected_upper = '/static/avatars/bodies/f/body_upper.png' if has_f_upper else '/static/avatars/bodies/m/body_upper.png'
        expected_lower = '/static/avatars/bodies/f/body_lower.png' if has_f_lower else '/static/avatars/bodies/m/body_lower.png'
        assert expected_upper == avatar['layer_map']['body-upper']['static_path']
        assert expected_lower == avatar['layer_map']['body-lower']['static_path']


def test_shared_and_body_specific_compatibility_rules():
    with flask_app.app_context():
        db.create_all()
        static_root = Path(flask_app.static_folder)

        shared_pkg = static_root / 'gear' / 'main_hand' / '__pytest_shared_item__' / 'shared' / 'front.png'
        legacy_m_chest = static_root / 'gear' / 'chest' / 'chest___pytest_m_only__.png'
        _touch(shared_pkg)
        _touch(legacy_m_chest)

        shared_item = GearItemDefinition(
            id='pytest_shared_item',
            slot_type='main_hand',
            name='Shared Tool',
            description='Shared package test item',
            image_key='__pytest_shared_item__',
            diamond_cost=1,
        )
        male_only_chest = GearItemDefinition(
            id='pytest_male_only_chest',
            slot_type='chest',
            name='Male Only Legacy Chest',
            description='Legacy chest compatibility test item',
            image_key='chest___pytest_m_only__.png',
            diamond_cost=1,
        )
        db.session.add(shared_item)
        db.session.add(male_only_chest)
        db.session.commit()

        try:
            assert is_item_variant_compatible_for_player(shared_item, 'm') is True
            assert is_item_variant_compatible_for_player(shared_item, 'f') is True
            assert is_item_variant_compatible_for_player(male_only_chest, 'm') is True
            assert is_item_variant_compatible_for_player(male_only_chest, 'f') is False
        finally:
            package_root = shared_pkg.parent.parent
            if package_root.exists():
                for file_path in sorted(package_root.rglob('*'), reverse=True):
                    if file_path.is_file():
                        file_path.unlink(missing_ok=True)
                    elif file_path.is_dir():
                        try:
                            file_path.rmdir()
                        except OSError:
                            pass
                try:
                    package_root.rmdir()
                except OSError:
                    pass
            legacy_m_chest.unlink(missing_ok=True)


def test_legacy_flat_gear_still_resolves_for_male_player():
    with flask_app.app_context():
        db.create_all()
        static_root = Path(flask_app.static_folder)
        legacy_chest = static_root / 'gear' / 'chest' / 'chest___pytest_legacy__.png'
        _touch(legacy_chest)

        chest_item = GearItemDefinition(
            id='pytest_legacy_chest',
            slot_type='chest',
            name='Legacy Chest',
            description='Legacy path resolution test item',
            image_key='chest___pytest_legacy__.png',
            diamond_cost=1,
        )
        player = Player(username='legacy_resolve_player', avatar_body_variant='m')
        player.set_password('pass1234')
        db.session.add(chest_item)
        db.session.add(player)
        db.session.flush()
        loadout = PlayerGearLoadout(player_id=player.id, chest_item_id=chest_item.id)
        db.session.add(loadout)
        db.session.commit()

        try:
            avatar = build_player_avatar_view(player, loadout)
            assert avatar['layer_map']['chest']['static_path'].endswith('/gear/chest/chest___pytest_legacy__.png')
        finally:
            legacy_chest.unlink(missing_ok=True)


def test_classic_template_includes_chest_underlay_layer():
    classic_template = Path(__file__).resolve().parents[1] / 'app' / 'templates' / 'player' / 'classic' / 'game.html'
    src = classic_template.read_text(encoding='utf-8')
    assert "'chest-underlay'" in src


def test_face_list_filters_by_variant_and_resets_incompatible_selection(monkeypatch):
    # Keep this contract independent of which faces artists have since added.
    monkeypatch.setattr('app.services.avatar._list_png_files',
                        lambda folder: ['face_001.png', 'face_f_001.png', 'face_test_m_only.png'])
    with flask_app.app_context():
        db.create_all()
        player = Player(username='variant_face_filter_player', selected_face_key='test_m_only')
        player.set_password('pass1234')
        db.session.add(player)
        db.session.commit()

        male_faces = list_available_face_keys('m')
        female_faces = list_available_face_keys('f')
        assert '001' in male_faces
        assert '001' in female_faces

        assert 'test_m_only' in male_faces
        assert 'test_m_only' not in female_faces
        set_player_body_variant(player, 'f')
        db.session.commit()
        assert player.avatar_body_variant == 'f'
        assert player.selected_face_key in female_faces


def test_avatar_female_package_layers_are_used_when_present():
    with flask_app.app_context():
        db.create_all()
        static_root = Path(flask_app.static_folder)
        f_front = static_root / 'gear' / 'chest' / '__pytest_pkg_chest__' / 'f' / 'front.png'
        m_front = static_root / 'gear' / 'chest' / '__pytest_pkg_chest__' / 'm' / 'front.png'
        _touch(f_front)
        _touch(m_front)
        try:
            item = GearItemDefinition(
                id='pytest_pkg_chest_item',
                slot_type='chest',
                name='Pkg Chest',
                description='Package chest item',
                image_key='__pytest_pkg_chest__',
                avatar_asset_key='__pytest_pkg_chest__',
                diamond_cost=1,
            )
            player = Player(username='variant_pkg_player', avatar_body_variant='f')
            player.set_password('pass1234')
            db.session.add(item)
            db.session.add(player)
            db.session.flush()
            loadout = PlayerGearLoadout(player_id=player.id, chest_item_id=item.id)
            db.session.add(loadout)
            db.session.commit()

            avatar = build_player_avatar_view(player, loadout)
            assert avatar['layer_map']['chest']['static_path'].endswith('/gear/chest/__pytest_pkg_chest__/f/front.png')
        finally:
            package_root = static_root / 'gear' / 'chest' / '__pytest_pkg_chest__'
            if package_root.exists():
                for file_path in sorted(package_root.rglob('*'), reverse=True):
                    if file_path.is_file():
                        file_path.unlink(missing_ok=True)
                    elif file_path.is_dir():
                        try:
                            file_path.rmdir()
                        except OSError:
                            pass
                try:
                    package_root.rmdir()
                except OSError:
                    pass


def test_legacy_icon_fallback_uses_avatar_asset_key_before_package_preview():
    with flask_app.app_context():
        db.create_all()
        static_root = Path(flask_app.static_folder)
        pkg_preview = static_root / 'gear' / 'chest' / '__pytest_pkg_icon__' / 'm' / 'front.png'
        legacy_icon = static_root / 'gear_icons' / 'chest' / 'chest_007.png'
        _touch(pkg_preview)
        legacy_icon.parent.mkdir(parents=True, exist_ok=True)
        if not legacy_icon.exists():
            legacy_icon.write_bytes(b'\x89PNG\r\n\x1a\n')
        try:
            resolved = resolve_gear_icon_static_path(
                slot_type='chest',
                image_key='__pytest_pkg_icon__',
                avatar_asset_key='007',
                avatar_body_variant='m',
            )
            assert resolved.endswith('/gear_icons/chest/chest_007.png')
        finally:
            package_root = static_root / 'gear' / 'chest' / '__pytest_pkg_icon__'
            if package_root.exists():
                for file_path in sorted(package_root.rglob('*'), reverse=True):
                    if file_path.is_file():
                        file_path.unlink(missing_ok=True)
                    elif file_path.is_dir():
                        try:
                            file_path.rmdir()
                        except OSError:
                            pass
                try:
                    package_root.rmdir()
                except OSError:
                    pass


def test_confirm_keeps_saved_female_variant_after_ajax_body_toggle():
    with flask_app.app_context():
        db.create_all()
        player = Player(username='variant_confirm_player', selected_face_key='003', avatar_body_variant='m')
        player.set_password('pass1234')
        db.session.add(player)
        db.session.commit()

    with flask_app.test_client() as client:
        _login(client, 'variant_confirm_player')
        js_headers = {'X-Requested-With': 'XMLHttpRequest'}
        body_resp = client.post(
            '/player/avatar/body',
            data={'variant': 'f', 'gear_filter': 'all', 'selected_item': ''},
            headers=js_headers,
            follow_redirects=False,
        )
        assert body_resp.status_code == 200

        confirm_resp = client.post(
            '/player/avatar/confirm',
            data={'avatar_body_variant': 'm'},
            follow_redirects=False,
        )
        assert confirm_resp.status_code in (301, 302)

    with flask_app.app_context():
        saved = Player.query.filter_by(username='variant_confirm_player').first()
        assert saved is not None
        assert saved.avatar_body_variant == 'f'
