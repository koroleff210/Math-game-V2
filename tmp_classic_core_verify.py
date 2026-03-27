from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app import create_app
from config import Config
from app.extensions import db, socketio
from app.models.player import Player
from app.models.subjects import Subject
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession, GameRound, RoundPlayer, PlayerAnswer
from app.models.classic import (
    ClassicRoundConfig,
    PlayerWallet,
    PlayerClassicState,
    PlayerProblemState,
    ProblemSolverCount,
    StoreItem,
    PlayerInventory,
)
from app.services.progression import ensure_session_participant_snapshot
from app.services.upgrade_catalog import UPGRADE_CATALOG
from app.modes.classic import state


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


app = create_app(TestConfig)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ''


checks: list[Check] = []


def check(name: str, ok: bool, detail: str = ''):
    checks.append(Check(name, bool(ok), detail))


def _login(flask_client, username: str, password: str):
    resp = flask_client.post('/login', data={'username': username, 'password': password}, follow_redirects=False)
    if resp.status_code not in (302, 303):
        raise AssertionError(f'login failed for {username}: {resp.status_code}')


class PlayerClient:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.flask = app.test_client()
        _login(self.flask, username, password)
        self.socket = socketio.test_client(app, flask_test_client=self.flask)
        if not self.socket.is_connected():
            raise AssertionError(f'socket not connected for {username}')

    def clear(self):
        self.socket.get_received()

    def emit(self, event: str, data: dict):
        self.socket.emit(event, data)
        return self.socket.get_received()

    def disconnect(self):
        try:
            self.socket.disconnect()
        except Exception:
            pass


def find_event(events, name: str):
    for e in events:
        if e['name'] == name:
            args = e.get('args', [])
            if args:
                return args[0]
            return {}
    return None


def last_event(events, name: str):
    found = [e for e in events if e['name'] == name]
    if not found:
        return None
    args = found[-1].get('args', [])
    return args[0] if args else {}


def get_player(username: str) -> Player:
    p = Player.query.filter_by(username=username).first()
    if not p:
        p = Player(username=username, is_admin=False)
        p.set_password('pw123')
        db.session.add(p)
        db.session.flush()
    else:
        p.set_password('pw123')
        db.session.flush()
    return p


def ensure_base_content(tag: str = 'coreverify'):
    subj = Subject.query.filter_by(name=f'{tag}-Math').first()
    if not subj:
        subj = Subject(name=f'{tag}-Math', description='core verify')
        db.session.add(subj)
        db.session.flush()
    topic = Topic.query.filter_by(name=f'{tag}-Arithmetic').first()
    if not topic:
        topic = Topic(name=f'{tag}-Arithmetic', subject_id=subj.id)
        db.session.add(topic)
        db.session.flush()

    defs = [
        ('P1', '2+2=?', '4'),
        ('P2', '3+3=?', '6'),
        ('P3', '5+5=?', '10'),
        ('P4', '7+1=?', '8'),
        ('P5', '9-4=?', '5'),
        ('P6', '11-1=?', '10'),
    ]
    problems = []
    for title, prompt, answer in defs:
        full_title = f'{tag}-{title}'
        prob = Problem.query.filter_by(title=full_title).first()
        if not prob:
            prob = Problem(title=full_title, prompt_text=prompt, answer_text=answer, difficulty=1, topic_id=topic.id)
            db.session.add(prob)
            db.session.flush()
        problems.append(prob)

    pset = ProblemSet.query.filter_by(name=f'{tag}-Set').first()
    if not pset:
        pset = ProblemSet(name=f'{tag}-Set', description='core verify set')
        db.session.add(pset)
        db.session.flush()
    existing = {prob.id for prob in pset.problems.all()}
    for prob in problems:
        if prob.id not in existing:
            pset.problems.append(prob)
    db.session.flush()
    return pset, problems
    return pset, problems


def clear_runtime_tables():
    for model in [PlayerAnswer, ProblemSolverCount, PlayerProblemState, PlayerInventory, PlayerClassicState, PlayerWallet, RoundPlayer, ClassicRoundConfig, GameRound, GameSession]:
        db.session.query(model).delete()
    db.session.commit()
    state.clear_session(1)


def create_session(config_overrides: dict, usernames: list[str], tag: str):
    pset, problems = ensure_base_content(tag)
    sess = GameSession(mode='classic', status='active', problem_set_id=pset.id, label=f'{tag}-session')
    db.session.add(sess)
    db.session.flush()
    round1 = GameRound(session_id=sess.id, round_number=1, started_at=datetime.now(timezone.utc))
    db.session.add(round1)
    db.session.flush()

    defaults = dict(
        mine_reward=20,
        treasure_search_reward=5,
        treasure_search_max_reward=5,
        attempts_per_problem=2,
        wrong_answer_penalty=3,
        bonus_timer_duration=0,
        bonus_timer_gold=0,
        first_solver_count=0,
        first_solver_multiplier=0,
        gem_milestone_count=0,
        gem_streak_count=0,
        gem_treasure_chance=0.0,
        steal_percent=0.10,
        steal_min_cap=5,
        steal_max_cap=50,
        steal_fallback_gold=5,
        steal_chest_count=0,
        steal_winning_chest_count=1,
        shield_duration=60,
        treasure_steal_token_chance=0.0,
        treasure_active_shield_chance=0.0,
        treasure_second_chance_chance=0.0,
    )
    defaults.update(config_overrides)
    cfg = ClassicRoundConfig(round_id=round1.id, **defaults)
    db.session.add(cfg)
    db.session.flush()

    state.init_session(sess.id, round1.started_at)

    players = []
    for uname in usernames:
        player = get_player(uname)
        players.append(player)
        db.session.add(RoundPlayer(session_id=sess.id, player_id=player.id))
        db.session.add(PlayerWallet(player_id=player.id, session_id=sess.id, gold=0, gems=0))
        db.session.add(PlayerClassicState(player_id=player.id, session_id=sess.id))
    db.session.flush()
    for p in players:
        ensure_session_participant_snapshot(sess.id, p.id)
    db.session.commit()
    return sess, round1, cfg, problems, {p.username: p for p in players}


def join(client: PlayerClient, session_id: int):
    client.clear()
    evs = client.emit('classic_join', {'session_id': session_id})
    ack = find_event(evs, 'join_ack')
    if ack is None:
        raise AssertionError(f'no join_ack for {client.username}: {evs}')
    return ack


def problem_id_by_title(join_ack: dict, title_suffix: str):
    for p in join_ack['problem_list']:
        if p['title'].endswith(title_suffix):
            return p['problem_id']
    raise KeyError(title_suffix)


def submit_correct(client: PlayerClient, session_id: int, problem_id: int, answer: str):
    client.clear()
    evs = client.emit('classic_submit_answer', {'session_id': session_id, 'problem_id': problem_id, 'answer_text': answer})
    prompt = find_event(evs, 'choose_action_prompt')
    if prompt is None:
        raise AssertionError(f'no choose_action_prompt for {client.username}: {evs}')
    return prompt


def submit_wrong(client: PlayerClient, session_id: int, problem_id: int, answer: str):
    client.clear()
    evs = client.emit('classic_submit_answer', {'session_id': session_id, 'problem_id': problem_id, 'answer_text': answer})
    res = find_event(evs, 'answer_result')
    if res is None:
        raise AssertionError(f'no answer_result for wrong answer {client.username}: {evs}')
    return res


def choose_action(client: PlayerClient, session_id: int, problem_id: int, action: str):
    client.clear()
    evs = client.emit('classic_choose_action', {'session_id': session_id, 'problem_id': problem_id, 'action': action})
    return evs


def set_wallet(username: str, session_id: int, *, gold=None, gems=None, steal_tokens=None):
    p = get_player(username)
    wallet = PlayerWallet.query.filter_by(player_id=p.id, session_id=session_id).first()
    if gold is not None:
        wallet.gold = gold
    if gems is not None:
        wallet.gems = gems
    if steal_tokens is not None:
        wallet.steal_tokens = steal_tokens
    db.session.commit()
    return wallet


def get_wallet(username: str, session_id: int):
    p = get_player(username)
    return PlayerWallet.query.filter_by(player_id=p.id, session_id=session_id).first()


def get_pcs(username: str, session_id: int):
    p = get_player(username)
    return PlayerClassicState.query.filter_by(player_id=p.id, session_id=session_id).first()


def add_second_chance(username: str, session_id: int):
    item = StoreItem.query.filter_by(session_id=session_id, bonus_type='shield', is_system=True).first()
    if not item:
        item = StoreItem(session_id=session_id, name='System SC', description='sys', cost=0, currency='gold', bonus_type='shield', session_stock=-1, per_player_limit=-1, is_system=True)
        db.session.add(item)
        db.session.flush()
    p = get_player(username)
    inv = PlayerInventory(player_id=p.id, session_id=session_id, item_id=item.id, purchased_at=datetime.now(timezone.utc), used_at=None)
    db.session.add(inv)
    db.session.commit()


def active_second_chance_count(username: str, session_id: int) -> int:
    p = get_player(username)
    return (
        PlayerInventory.query.join(StoreItem, PlayerInventory.item_id == StoreItem.id)
        .filter(PlayerInventory.player_id == p.id, PlayerInventory.session_id == session_id, StoreItem.bonus_type == 'shield', PlayerInventory.used_at == None)
        .count()
    )


def active_bonus_counts(username: str, session_id: int):
    from app.modes.classic import store as classic_store
    p = get_player(username)
    return classic_store.get_active_counts(p.id, session_id)


def ensure_store_item(session_id: int, bonus_type: str, cost: int = 1):
    item = StoreItem.query.filter_by(session_id=session_id, bonus_type=bonus_type).first()
    if item:
        return item
    item = StoreItem(session_id=session_id, name=bonus_type, description=bonus_type, cost=cost, currency='gold', bonus_type=bonus_type, session_stock=-1, per_player_limit=-1, is_system=False)
    db.session.add(item)
    db.session.commit()
    return item


def buy_item(client: PlayerClient, session_id: int, item_id: int):
    client.clear()
    evs = client.emit('classic_buy_item', {'session_id': session_id, 'item_id': item_id})
    res = find_event(evs, 'buy_result')
    if res is None:
        raise AssertionError(f'no buy_result for {client.username}: {evs}')
    return res


def steal_pick_target(client: PlayerClient, session_id: int, target_player_id: int):
    client.clear()
    evs = client.emit('classic_steal_pick_target', {'session_id': session_id, 'target_player_id': target_player_id})
    return evs


def steal_cancel(client: PlayerClient, session_id: int):
    client.clear()
    evs = client.emit('classic_steal_cancel', {'session_id': session_id})
    return evs


def mini_pick(client: PlayerClient, session_id: int, chest_index: int):
    client.clear()
    evs = client.emit('classic_steal_mini_game_pick', {'session_id': session_id, 'chest_index': chest_index})
    return evs


def main():
    with app.app_context():
        clear_runtime_tables()
        # Ensure baseline users exist and passwords known
        # Ensure baseline users exist and passwords known
        for name in ['verify_p1', 'verify_p2']:
            get_player(name)
        for name in ['player1', 'player2']:
            p = Player.query.filter_by(username=name).first()
            if p:
                p.set_password('player123')
        admin = Player.query.filter_by(username='admin').first()
        if admin:
            admin.set_password('admin123')
        db.session.commit()

        # Inspection checks
        from app.modes.classic.forms import ClassicSessionForm
        cfg_fields = [
            'mine_reward','treasure_search_reward','treasure_search_max_reward','attempts_per_problem','wrong_answer_penalty',
            'bonus_timer_duration','bonus_timer_gold','first_solver_count','first_solver_multiplier','gem_milestone_count',
            'gem_streak_count','gem_treasure_chance','steal_percent','steal_min_cap','steal_max_cap','steal_fallback_gold',
            'steal_chest_count','steal_winning_chest_count','shield_duration','treasure_steal_token_chance',
            'treasure_active_shield_chance','treasure_second_chance_chance'
        ]
        for f in cfg_fields:
            check(f'config field present: {f}', hasattr(ClassicSessionForm, f))

        # Clients
        p1 = PlayerClient('verify_p1', 'pw123')
        p2 = PlayerClient('verify_p2', 'pw123')

        # Gem + mine + penalty + attempts
        sess, rnd, cfg, probs, _ = create_session(
            {'mine_reward': 20, 'attempts_per_problem': 2, 'wrong_answer_penalty': 3, 'gem_milestone_count': 2, 'gem_streak_count': 2},
            ['verify_p1', 'verify_p2'],
            'v1'
        )
        ack1 = join(p1, sess.id)
        pid1 = problem_id_by_title(ack1, 'P1')
        pid2 = problem_id_by_title(ack1, 'P2')
        wrong = submit_wrong(p1, sess.id, pid1, '999')
        check('wrong penalty applied', wrong['gold_after_penalty'] == 0 and wrong['attempts_left'] == 1, str(wrong))
        submit_correct(p1, sess.id, pid1, '4')
        res = find_event(choose_action(p1, sess.id, pid1, 'mine'), 'reward_applied')
        check('mine reward uses configured base', res is not None and res['gold_gained'] == 20, str(res))
        submit_correct(p1, sess.id, pid2, '6')
        res2 = find_event(choose_action(p1, sess.id, pid2, 'mine'), 'reward_applied')
        check('gem milestone+streak fire at configured thresholds', res2 is not None and res2['gems_gained'] == 2 and res2['gem_reason'] == 'both', str(res2))
        pid3 = problem_id_by_title(ack1, 'P3')
        wrong2 = submit_wrong(p1, sess.id, pid3, '999')
        wrong3 = submit_wrong(p1, sess.id, pid3, '999')
        check('attempts_per_problem closes after configured limit', wrong3['problem_closed'] is True and wrong3['attempts_left'] == 0, str(wrong3))
        state.clear_session(sess.id)

        # Treasure gem
        sess, rnd, cfg, probs, _ = create_session({'gem_treasure_chance': 1.0}, ['verify_p1'], 'v2')
        ack = join(p1, sess.id)
        pid = problem_id_by_title(ack, 'P1')
        submit_correct(p1, sess.id, pid, '4')
        with patch('app.modes.classic.engine.random.randint', return_value=5), patch('app.modes.classic.engine.random.random', return_value=0.0):
            res = find_event(choose_action(p1, sess.id, pid, 'treasure_search'), 'reward_applied')
        check('treasure gem chance 1.0 grants gem', res is not None and res['treasure_gem_won'] is True and res['gems_gained'] == 1 and not res['token_found'] and not res['treasure_shield_granted'] and not res['treasure_second_chance_granted'], str(res))
        state.clear_session(sess.id)

        # Treasure token grant and blocked at cap
        sess, rnd, cfg, probs, _ = create_session({'treasure_steal_token_chance': 1.0}, ['verify_p1'], 'v3')
        ack = join(p1, sess.id)
        pid = problem_id_by_title(ack, 'P1')
        set_wallet('verify_p1', sess.id, steal_tokens=0)
        submit_correct(p1, sess.id, pid, '4')
        with patch('app.modes.classic.engine.random.randint', return_value=5), patch('app.modes.classic.engine.random.random', return_value=0.0):
            res = find_event(choose_action(p1, sess.id, pid, 'treasure_search'), 'reward_applied')
        check('treasure token chance 1.0 grants token when under cap', res is not None and res['token_found'] is True and res['token_awarded'] is True and get_wallet('verify_p1', sess.id).steal_tokens == 1, str(res))
        pid2 = problem_id_by_title(ack, 'P2')
        submit_correct(p1, sess.id, pid2, '6')
        with patch('app.modes.classic.engine.random.randint', return_value=5), patch('app.modes.classic.engine.random.random', return_value=0.0):
            res2 = find_event(choose_action(p1, sess.id, pid2, 'treasure_search'), 'reward_applied')
        check('blocked treasure token resolves to nothing without reroll', res2 is not None and res2['token_found'] is True and res2['token_awarded'] is False and res2['gems_gained'] == 0 and not res2['treasure_shield_granted'] and not res2['treasure_second_chance_granted'], str(res2))
        state.clear_session(sess.id)

        # Active shield from treasure
        sess, rnd, cfg, probs, _ = create_session({'treasure_active_shield_chance': 1.0, 'shield_duration': 77}, ['verify_p1'], 'v4')
        ack = join(p1, sess.id)
        pid = problem_id_by_title(ack, 'P1')
        submit_correct(p1, sess.id, pid, '4')
        with patch('app.modes.classic.engine.random.randint', return_value=5), patch('app.modes.classic.engine.random.random', return_value=0.0):
            res = find_event(choose_action(p1, sess.id, pid, 'treasure_search'), 'reward_applied')
        pcs = get_pcs('verify_p1', sess.id)
        check('active shield from treasure chance 1.0 grants shield', res is not None and res['treasure_shield_granted'] is True and pcs and pcs.shield_expires_at is not None, str(res))
        if pcs and pcs.shield_expires_at:
            delta = (pcs.shield_expires_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds()
            check('active shield from treasure uses configured shield_duration', 65 <= delta <= 77.5, f'delta={delta}')
        state.clear_session(sess.id)

        # Second chance grant and blocked case
        sess, rnd, cfg, probs, _ = create_session({'treasure_second_chance_chance': 1.0}, ['verify_p1'], 'v5')
        ack = join(p1, sess.id)
        pid = problem_id_by_title(ack, 'P1')
        submit_correct(p1, sess.id, pid, '4')
        with patch('app.modes.classic.engine.random.randint', return_value=5), patch('app.modes.classic.engine.random.random', return_value=0.0):
            res = find_event(choose_action(p1, sess.id, pid, 'treasure_search'), 'reward_applied')
        check('second chance from treasure chance 1.0 grants inventory-backed SC', res is not None and res['treasure_second_chance_granted'] is True and active_second_chance_count('verify_p1', sess.id) == 1, str(res))
        pid2 = problem_id_by_title(ack, 'P2')
        submit_correct(p1, sess.id, pid2, '6')
        with patch('app.modes.classic.engine.random.randint', return_value=5), patch('app.modes.classic.engine.random.random', return_value=0.0):
            res2 = find_event(choose_action(p1, sess.id, pid2, 'treasure_search'), 'reward_applied')
        check('blocked second chance resolves to nothing without reroll', res2 is not None and res2['treasure_second_chance_granted'] is False and active_second_chance_count('verify_p1', sess.id) == 1, str(res2))
        state.clear_session(sess.id)

        # Nothing outcome + exactly one side reward mapping
        sess, rnd, cfg, probs, _ = create_session({'gem_treasure_chance': 0.5, 'treasure_steal_token_chance': 0.5}, ['verify_p1'], 'v6')
        ack = join(p1, sess.id)
        pid = problem_id_by_title(ack, 'P1')
        set_wallet('verify_p1', sess.id, steal_tokens=0)
        submit_correct(p1, sess.id, pid, '4')
        with patch('app.modes.classic.engine.random.randint', return_value=5), patch('app.modes.classic.engine.random.random', return_value=0.25):
            gem_res = find_event(choose_action(p1, sess.id, pid, 'treasure_search'), 'reward_applied')
        check('treasure side reward grants exactly one reward (gem bucket)', gem_res is not None and gem_res['treasure_gem_won'] is True and gem_res['token_found'] is False and not gem_res['treasure_shield_granted'] and not gem_res['treasure_second_chance_granted'], str(gem_res))
        pid2 = problem_id_by_title(ack, 'P2')
        submit_correct(p1, sess.id, pid2, '6')
        with patch('app.modes.classic.engine.random.randint', return_value=5), patch('app.modes.classic.engine.random.random', return_value=0.75):
            tok_res = find_event(choose_action(p1, sess.id, pid2, 'treasure_search'), 'reward_applied')
        check('treasure side reward grants exactly one reward (token bucket)', tok_res is not None and tok_res['treasure_gem_won'] is False and tok_res['token_found'] is True and not tok_res['treasure_shield_granted'] and not tok_res['treasure_second_chance_granted'], str(tok_res))
        sess2, rnd2, cfg2, probs2, _ = create_session({}, ['verify_p1'], 'v6b')
        ack2 = join(p1, sess2.id)
        pidn = problem_id_by_title(ack2, 'P1')
        submit_correct(p1, sess2.id, pidn, '4')
        with patch('app.modes.classic.engine.random.randint', return_value=5), patch('app.modes.classic.engine.random.random', return_value=0.99):
            nothing_res = find_event(choose_action(p1, sess2.id, pidn, 'treasure_search'), 'reward_applied')
        check('subtotal < 1 supports nothing outcome', nothing_res is not None and not nothing_res['treasure_gem_won'] and not nothing_res['token_found'] and not nothing_res['treasure_shield_granted'] and not nothing_res['treasure_second_chance_granted'], str(nothing_res))
        state.clear_session(sess.id)
        state.clear_session(sess2.id)

        # Steal percent/min/max/fallback/chest config
        sess, rnd, cfg, probs, players = create_session({'steal_percent': 0.30, 'steal_min_cap': 5, 'steal_max_cap': 25, 'steal_fallback_gold': 9, 'steal_chest_count': 0}, ['verify_p1', 'verify_p2'], 'v7')
        ack1 = join(p1, sess.id)
        join(p2, sess.id)
        set_wallet('verify_p1', sess.id, gold=0, steal_tokens=1)
        set_wallet('verify_p2', sess.id, gold=100, steal_tokens=1)
        pid = problem_id_by_title(ack1, 'P1')
        submit_correct(p1, sess.id, pid, '4')
        targets = find_event(choose_action(p1, sess.id, pid, 'steal'), 'steal_targets')
        check('steal with valid targets emits target list', targets is not None and len(targets['targets']) == 1, str(targets))
        res = find_event(steal_pick_target(p1, sess.id, players['verify_p2'].id), 'steal_result')
        check('steal_percent/min/max applied to runtime steal amount', res is not None and res['gold_gained'] == 25, str(res))
        set_wallet('verify_p1', sess.id, gold=0, steal_tokens=1)
        set_wallet('verify_p2', sess.id, gold=10, steal_tokens=1)
        pid2 = problem_id_by_title(ack1, 'P2')
        submit_correct(p1, sess.id, pid2, '6')
        targets2 = find_event(choose_action(p1, sess.id, pid2, 'steal'), 'steal_targets')
        res2 = find_event(steal_pick_target(p1, sess.id, players['verify_p2'].id), 'steal_result')
        check('steal_min_cap applies when percent result is below min', res2 is not None and res2['gold_gained'] == 5, str(res2))
        set_wallet('verify_p1', sess.id, gold=0, steal_tokens=1)
        set_wallet('verify_p2', sess.id, gold=0, steal_tokens=1)
        pid3 = problem_id_by_title(ack1, 'P3')
        submit_correct(p1, sess.id, pid3, '10')
        fallback = find_event(choose_action(p1, sess.id, pid3, 'steal'), 'steal_result')
        check('steal_fallback_gold applied when no valid targets exist', fallback is not None and fallback['outcome'] == 'no_targets_fallback' and fallback['gold_gained'] == 9, str(fallback))
        state.clear_session(sess.id)

        # Mini-game chest count / winning count + cancel semantics
        sess, rnd, cfg, probs, players = create_session({'steal_chest_count': 4, 'steal_winning_chest_count': 2}, ['verify_p1', 'verify_p2'], 'v8')
        ack1 = join(p1, sess.id)
        join(p2, sess.id)
        set_wallet('verify_p1', sess.id, gold=0, steal_tokens=1)
        set_wallet('verify_p2', sess.id, gold=50, steal_tokens=1)
        pid = problem_id_by_title(ack1, 'P1')
        submit_correct(p1, sess.id, pid, '4')
        targets = find_event(choose_action(p1, sess.id, pid, 'steal'), 'steal_targets')
        check('steal target selection opens before mini-game', targets is not None and len(targets['targets']) == 1, str(targets))
        mg = find_event(steal_pick_target(p1, sess.id, players['verify_p2'].id), 'steal_mini_game_start')
        check('mini-game uses configured chest count and winning count', mg is not None and mg['chest_count'] == 4 and mg['winning_chest_count'] == 2, str(mg))
        set_wallet('verify_p1', sess.id, steal_tokens=1)
        pid2 = problem_id_by_title(ack1, 'P2')
        submit_correct(p1, sess.id, pid2, '6')
        choose_action(p1, sess.id, pid2, 'steal')
        cancel = find_event(steal_cancel(p1, sess.id), 'choose_action_prompt')
        check('steal cancel preserves token and action slot', cancel is not None and get_wallet('verify_p1', sess.id).steal_tokens == 1, str(cancel))
        state.clear_session(sess.id)

        # Timer bonus + first solver bonus
        p1.disconnect()
        p2.disconnect()
        p1 = PlayerClient('verify_p1', 'pw123')
        p2 = PlayerClient('verify_p2', 'pw123')
        sess, rnd, cfg, probs, _ = create_session({'mine_reward': 20, 'bonus_timer_duration': 30, 'bonus_timer_gold': 7, 'first_solver_count': 2, 'first_solver_multiplier': 3}, ['verify_p1', 'verify_p2'], 'v9')
        ack1 = join(p1, sess.id)
        join(p2, sess.id)
        pid = problem_id_by_title(ack1, 'P1')
        state.init_session(sess.id, datetime.now(timezone.utc))
        submit_correct(p1, sess.id, pid, '4')
        res = find_event(choose_action(p1, sess.id, pid, 'mine'), 'reward_applied')
        check('timer bonus and first-solver bonus both apply when configured', res is not None and res['gold_gained'] == 33, str(res))
        pid2 = problem_id_by_title(ack1, 'P2')
        state.init_session(sess.id, datetime.now(timezone.utc) - timedelta(seconds=40))
        submit_correct(p1, sess.id, pid2, '6')
        res2 = find_event(choose_action(p1, sess.id, pid2, 'mine'), 'reward_applied')
        check('timer bonus disabled after configured window', res2 is not None and res2['gold_gained'] == 26, str(res2))
        pid_shared = problem_id_by_title(ack1, 'P3')
        state.init_session(sess.id, datetime.now(timezone.utc) - timedelta(seconds=40))
        submit_correct(p1, sess.id, pid_shared, '10')
        first_res = find_event(choose_action(p1, sess.id, pid_shared, 'mine'), 'reward_applied')
        p2.disconnect()
        p2 = PlayerClient('verify_p2', 'pw123')
        join(p2, sess.id)
        submit_correct(p2, sess.id, pid_shared, '10')
        second_res = find_event(choose_action(p2, sess.id, pid_shared, 'mine'), 'reward_applied')
        check('first solver bonus fields affect rank 1 and rank 2 rewards', first_res is not None and second_res is not None and first_res['gold_gained'] == 26 and second_res['gold_gained'] == 23, f'first={first_res} second={second_res}')
        state.clear_session(sess.id)

        # Store purchase cap enforcement for steal token
        sess, rnd, cfg, probs, _ = create_session({}, ['verify_p1'], 'v10')
        join(p1, sess.id)
        item = ensure_store_item(sess.id, 'steal_token', cost=1)
        set_wallet('verify_p1', sess.id, gold=10, steal_tokens=1)
        res = buy_item(p1, sess.id, item.id)
        check('store purchase blocks steal token at cap', res['ok'] is False and 'maximum steal tokens' in res['message'], str(res))
        state.clear_session(sess.id)

        # Final cleanup of runtime state tables created by this script
        p1.disconnect()
        p2.disconnect()
        clear_runtime_tables()

    failed = [c for c in checks if not c.ok]
    print('CLASSIC CORE VERIFY RESULTS')
    for c in checks:
        status = 'PASS' if c.ok else 'FAIL'
        print(f'{status} | {c.name} | {c.detail}')
    print(f'TOTAL={len(checks)} PASS={len(checks)-len(failed)} FAIL={len(failed)}')
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()



