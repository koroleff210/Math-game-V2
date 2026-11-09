"""Round instructions must reflect admin configuration, including disabled rewards."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bs4 import BeautifulSoup
from flask import render_template
from app import create_app
from app.modes.classic.engine import treasure_enabled
from app.services.overlay_layouts import build_overlay_asset_payload, load_overlay_layouts


class Config:
    TESTING = True
    SECRET_KEY = 'isolated-classic-design'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SOCKETIO_ASYNC_MODE = 'threading'
    WTF_CSRF_ENABLED = False


def render_rules(**overrides):
    app = create_app(Config)
    values = dict(mine_reward=37, steal_percent=.125, treasure_search_reward=8, treasure_search_max_reward=23,
                  attempts_per_problem=2, wrong_answer_penalty=4, bonus_timer_duration=45,
                  bonus_timer_gold=9, gem_treasure_chance=.5, treasure_steal_token_chance=.3,
                  treasure_active_shield_chance=0, treasure_second_chance_chance=0,
                  first_solver_count=3, first_solver_multiplier=2)
    values.update(overrides)
    with app.test_request_context('/classic/game/1'):
        html = render_template('player/classic/game.html',
            game_session=SimpleNamespace(id=1, status='active'),
            player=SimpleNamespace(username='Preview'),
            game_round=SimpleNamespace(id=1, round_number=1, started_at=datetime.now(timezone.utc)),
            round_config=SimpleNamespace(**values), gear_avatar=SimpleNamespace(layer_map={}),
            treasure_enabled=treasure_enabled(SimpleNamespace(**values)),
            round_background_urls=[], current_round_background_url=None,
            overlay_assets=build_overlay_asset_payload(), overlay_layouts=load_overlay_layouts())
    return BeautifulSoup(html, 'html.parser')


def test_zero_treasure_hides_button_and_round_rule():
    page = render_rules(treasure_search_reward=0, treasure_search_max_reward=0,
                        gem_treasure_chance=0, treasure_steal_token_chance=0)
    assert page.select_one('#btn-treasure-search')['style'] == 'display:none'
    assert 'Treasure: earn' not in page.select_one('.round-rules').get_text(' ', strip=True)


def test_rules_use_admin_values_and_only_enabled_reward_types():
    page = render_rules()
    rules = page.select_one('.round-rules')
    text = rules.get_text(' ', strip=True)
    assert 'Mine: earn 37' in text
    assert 'Treasure: earn 8–23' in text
    assert '2 attempts per problem' in text
    assert 'Wrong answer: lose 4' in text
    assert [icon['aria-label'] for icon in rules.select('.rule-extra .resource-icon')] == ['gem', 'steal token']
    assert page.select_one('#timer-bonus-display')['data-bonus-duration'] == '45'
    assert page.select_one('#timer-bonus-display')['data-bonus-gold'] == '9'


def test_fixed_treasure_amount_and_unlimited_attempts():
    page = render_rules(treasure_search_reward=11, treasure_search_max_reward=11, attempts_per_problem=-1)
    text = page.select_one('.round-rules').get_text(' ', strip=True)
    assert 'Treasure: earn 11' in text and '11–11' not in text
    assert 'Unlimited attempts per problem' in text


def test_action_buttons_show_configured_rewards_and_existing_art():
    page = render_rules()
    assert page.select_one('#btn-mine').get_text(' ', strip=True) == 'Mine 37'
    assert page.select_one('#btn-mine .resource-icon')['aria-label'] == 'gold'
    assert page.select_one('#btn-steal').get_text(' ', strip=True) == 'Steal 12.5%'
    assert page.select_one('#btn-treasure-search .resource-icon')['aria-label'] == 'chest'
    assert page.select_one('#btn-treasure-search img')['src'].endswith('.webp')
    page = render_rules(mine_reward=0, steal_percent=.1)
    assert page.select_one('#btn-mine').get_text(' ', strip=True) == 'Mine 0'
    assert page.select_one('#btn-steal').get_text(' ', strip=True) == 'Steal 10%'


def test_disabled_treasure_extras_are_not_advertised():
    page = render_rules(gem_treasure_chance=0, treasure_steal_token_chance=0,
                        treasure_active_shield_chance=0, treasure_second_chance_chance=0,
                        bonus_timer_duration=0, bonus_timer_gold=0)
    assert not page.select('.rule-extra')
    assert page.select_one('#timer-bonus-row').has_attr('hidden')
