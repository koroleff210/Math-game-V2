import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import render_template_string

from app import create_app


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'classic-token-icons-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False


def test_token_icon_macro_uses_assets_and_safe_fallbacks():
    app = create_app(_TestConfig)
    with app.test_request_context('/'):
        html = render_template_string(
            '{% from "shared/_token_icon.html" import token_icon %}'
            '{{ token_icon("steal_shield", "small", compact=True) }}'
            '{{ token_icon("x2_mine", "small", compact=True) }}'
        )

    assert 'classic_ui/icons/shield.png' in html
    assert 'token-icon-fallback' in html
    assert 'x2M' in html


def test_classic_player_template_contains_token_icon_hooks():
    source_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'app',
        'templates',
        'player',
        'classic',
        'game.html',
    )
    with open(source_path, encoding='utf-8') as fh:
        source = fh.read()

    assert 'TOKEN_ICON_DEFS' in source
    assert 'store-token-card__icon' in source
    assert 'store-token-card__topline' in source
    assert 'store-token-card__name' in source
    assert 'store-token-card__description' in source
    assert 'store-token-card__price' in source
    assert 'store-token-card__buy' in source
    assert 'steal-token-icon-slot' in source
    assert 'shield-token-icon-slot' in source
    assert "tokenBadgeHtml('steal_token'" in source
    assert "\\'none\\'" not in source
    assert 'this.hidden=true;this.nextElementSibling.hidden=false;' in source


def test_admin_classic_templates_use_shared_token_icon_macro():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    store_path = os.path.join(root, 'app', 'templates', 'admin', 'classic', 'store.html')
    manage_path = os.path.join(root, 'app', 'templates', 'admin', 'classic', 'manage.html')

    with open(store_path, encoding='utf-8') as fh:
        store_source = fh.read()
    with open(manage_path, encoding='utf-8') as fh:
        manage_source = fh.read()

    assert 'shared/_token_icon.html' in store_source
    assert 'token_icon(item.bonus_type' in store_source
    assert 'shared/_token_icon.html' in manage_source
    assert "token_icon('steal_token'" in manage_source
