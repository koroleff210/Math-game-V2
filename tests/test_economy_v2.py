"""Economy integration checks use isolated databases and real socket handlers."""
from datetime import datetime, timezone
from pathlib import Path
import random
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_classic_realtime_delivery import game, payload
from app.extensions import db
from app.models.classic import ClassicRoundConfig, PlayerWallet, PlayerProblemState, PlayerInventory, StoreItem
from app.models.game import GameSession, GameRound
from app.models.problems import Problem
from app.models.progression import PlayerProgression
from app.models.economy import GoldTransaction
from app.models.gear import GearItemDefinition
from app.services.economy import settle_session, capped_permanent_bonus, seed_session_store
from app.modes.classic import state, engine, store
from app.services.gear import purchase_blacksmith_gear


def setup_round(game, count=20):
    app, ids, clients, connect = game
    with app.app_context():
        session = db.session.get(GameSession, ids['session'])
        cfg = ClassicRoundConfig.query.one()
        cfg.mine_reward=5; cfg.steal_percent=.12; cfg.steal_max_cap=15; cfg.steal_min_cap=0
        cfg.steal_chest_count=7; cfg.steal_winning_chest_count=3
        for i in range(count-2):
            p = Problem(topic_id=session.problem_set.problems[0].topic_id, title=f'Extra {i}', prompt_text='2+2', answer_text='4')
            session.problem_set.problems.append(p)
        db.session.commit()
        ids['problems']=[p.id for p in session.problem_set.problems]
    clients['actor'].post('/classic/join', data={'session_id':ids['session']})
    sock=connect('actor');sock.emit('classic_join',{'session_id':ids['session']});sock.get_received()
    return sock


def answer(sock, ids, problem_id, correct=True, action='mine'):
    sock.emit('classic_submit_answer',dict(session_id=ids['session'], problem_id=problem_id,answer_text='4' if correct else 'wrong'))
    events=sock.get_received()
    if correct:
        prompt=payload(events,'choose_action_prompt')
        sock.emit('classic_choose_action',dict(session_id=ids['session'],problem_id=problem_id,action=action))
        return prompt,sock.get_received()
    return None,events


def test_typical_session_banks_once_and_expires_gems(game):
    app,ids,clients,connect=game;sock=setup_round(game)
    for i,p in enumerate(ids['problems']):answer(sock,ids,p,correct=i%4!=3)
    with app.app_context():
        wallet=PlayerWallet.query.filter_by(player_id=ids['actor']).one()
        assert wallet.correct_answers==15 and wallet.gems==3
        assert 150 <= wallet.gold <=170
        expected=wallet.gold
        session=db.session.get(GameSession,ids['session']);session.status='finished'
        assert settle_session(session);db.session.commit()
        assert not settle_session(session);db.session.commit()
        assert PlayerProgression.query.filter_by(player_id=ids['actor']).one().saved_gold==expected
        assert wallet.gems==0 and wallet.gold==expected
        assert GoldTransaction.query.count()==1
        # Expire ORM state as on reconnect/restart; settlement stays idempotent.
        db.session.expire_all();assert not settle_session(db.session.get(GameSession,ids['session']))
        from app.models.player import Player
        db.session.get(Player,ids['actor']).character_locked_at=datetime.now(timezone.utc)
        db.session.commit()
    hub=clients['actor'].get('/player/dashboard',headers={'Sec-Fetch-Dest':'iframe'})
    assert hub.status_code==200 and b'Saved gold' in hub.data
    shop=clients['actor'].get('/player/blacksmith?tab=gear',headers={'Sec-Fetch-Dest':'iframe'})
    assert shop.status_code==200 and b'Saved gold' in shop.data


def test_correct_reward_is_immediate_and_cannot_be_replayed(game):
    app,ids,*_=game;sock=setup_round(game,2)
    sock.emit('classic_submit_answer',dict(session_id=ids['session'],problem_id=ids['problems'][0],answer_text='4'))
    assert payload(sock.get_received(),'choose_action_prompt')['new_balance']==5
    state.clear_session(ids['session'])
    sock.emit('classic_submit_answer',dict(session_id=ids['session'],problem_id=ids['problems'][0],answer_text='4'))
    payload(sock.get_received(),'error')
    with app.app_context():assert PlayerWallet.query.filter_by(player_id=ids['actor']).one().gold==5


def test_session_milestone_survives_new_round_and_reconnect(game):
    app,ids,clients,connect=game;sock=setup_round(game,5)
    for p in ids['problems'][:4]:answer(sock,ids,p)
    with app.app_context():
        old=GameRound.query.one();old.ended_at=datetime.now(timezone.utc)
        new=GameRound(session_id=ids['session'],round_number=2,started_at=datetime.now(timezone.utc));db.session.add(new);db.session.flush()
        db.session.add(ClassicRoundConfig(round_id=new.id));db.session.commit()
    state.clear_session(ids['session']);sock.disconnect();sock=connect('actor')
    sock.emit('classic_join',{'session_id':ids['session']});ack=payload(sock.get_received(),'join_ack');assert ack['streak']==4
    result,_=answer(sock,ids,ids['problems'][4])
    assert result['new_gems']==1 and result['streak']==5


def test_treasure_pity_selected_only_and_resets_on_reward(game,monkeypatch):
    app,ids,*_=game;sock=setup_round(game,5)
    with app.app_context():
        cfg=ClassicRoundConfig.query.one();cfg.gem_treasure_chance=.35
        cfg.treasure_double_mine_chance=cfg.treasure_steal_token_chance=cfg.treasure_active_shield_chance=cfg.treasure_second_chance_chance=0
        db.session.commit()
    monkeypatch.setattr(random,'random',lambda:.60)
    for i,p in enumerate(ids['problems'][:4]):
        _,events=answer(sock,ids,p,action='treasure_search');payload(events,'treasure_chest_offer')
        sock.emit('classic_treasure_pick_chest',{'session_id':ids['session'],'chest_index':1})
        result=payload(sock.get_received(),'treasure_chest_result')
        assert result['selected_reward_granted']==(i==3)
        # Duplicate selection cannot mint another gem or increase failure count.
        sock.emit('classic_treasure_pick_chest',{'session_id':ids['session'],'chest_index':1});sock.get_received()
        sock.emit('classic_stage_event_closed',{'session_id':ids['session'],'event_type':'treasure'});sock.get_received()
    with app.app_context():
        wallet=PlayerWallet.query.filter_by(player_id=ids['actor']).one()
        assert wallet.treasure_failures==0 and wallet.gems==1


def test_permanent_cap_and_standardized_mode(game):
    app,ids,*_=game
    with app.app_context():
        cfg=ClassicRoundConfig.query.one();wallet=PlayerWallet(session_id=ids['session'],player_id=ids['actor'],gold=0,gems=0)
        db.session.add(wallet);db.session.flush()
        assert sum(capped_permanent_bonus(wallet,cfg,999,7) for _ in range(100))==70
        cfg.standardized_competition=True
        assert capped_permanent_bonus(wallet,cfg,999,10)==0


def test_new_wallet_and_legacy_sessions_are_not_retroactively_paid(game):
    app,ids,*_=game
    with app.app_context():
        s=db.session.get(GameSession,ids['session']);s.economy_version=1;s.status='finished'
        db.session.add(PlayerWallet(session_id=s.id,player_id=ids['actor'],gold=150,gems=3))
        db.session.flush();assert not settle_session(s)
        assert GoldTransaction.query.count()==0
        fresh=GameSession(mode='classic',status='waiting');db.session.add(fresh);db.session.flush()
        from app.services.economy import session_wallet
        wallet=session_wallet(fresh.id,ids['actor']);assert wallet.gold==wallet.gems==wallet.correct_answers==wallet.treasure_failures==wallet.steal_attempts==0


def test_store_gem_prices_and_stacking_limits(game):
    app,ids,*_=game;sock=setup_round(game,2)
    with app.app_context():
        seed_session_store(ids['session']);db.session.commit()
        wallet=PlayerWallet.query.filter_by(player_id=ids['actor']).one();wallet.gems=4;db.session.commit()
        items=StoreItem.query.filter_by(session_id=ids['session']).all()
        assert all(i.currency=='gems' and 1<=i.cost<=2 for i in items)
        item=next(i for i in items if i.bonus_type=='x2_mine')
        assert store.purchase_item(ids['actor'],ids['session'],item.id)[0]
        assert not store.purchase_item(ids['actor'],ids['session'],item.id)[0]
        assert wallet.gems==2
    _,events=answer(sock,ids,ids['problems'][0]);assert payload(events,'reward_applied')['gold_gained']==10


def test_saved_gold_purchase_preserves_diamonds(game):
    app,ids,*_=game
    with app.app_context():
        db.session.add(PlayerProgression(player_id=ids['actor'],saved_gold=500,diamonds_balance=9))
        db.session.add(GearItemDefinition(id='test_cosmetic',name='Cosmetic',slot_type='head',gold_cost=300,diamond_cost=1))
        db.session.commit()
        result=purchase_blacksmith_gear(player_id=ids['actor'],item_id='test_cosmetic');db.session.commit()
        assert result['new_balance']==200
        assert PlayerProgression.query.one().diamonds_balance==9
        assert GoldTransaction.query.one().amount_delta==-300
        import pytest
        with pytest.raises(ValueError,match='already own'):purchase_blacksmith_gear(player_id=ids['actor'],item_id='test_cosmetic')


def test_steal_attempts_are_session_limited(game):
    app,ids,*_=game;sock=setup_round(game,3)
    with app.app_context():
        wallet=PlayerWallet.query.filter_by(player_id=ids['actor']).one();wallet.steal_tokens=3;db.session.commit()
    for p in ids['problems'][:2]:answer(sock,ids,p,action='steal')
    sock.emit('classic_submit_answer',dict(session_id=ids['session'],problem_id=ids['problems'][2],answer_text='4'))
    assert payload(sock.get_received(),'choose_action_prompt')['steal_available'] is False
    sock.emit('classic_choose_action',dict(session_id=ids['session'],problem_id=ids['problems'][2],action='steal'))
    payload(sock.get_received(),'error')
    with app.app_context():assert PlayerWallet.query.filter_by(player_id=ids['actor']).one().steal_attempts==2


def test_multiplayer_transfer_simulation_preserves_gold():
    rng=random.Random(42);balances=[160]*30
    for _ in range(5000):
        a,b=rng.sample(range(30),2)
        amount=engine.calc_steal_amount(balances[b],.12,0,15)
        if rng.randrange(7)<3:balances[a]+=amount;balances[b]-=amount
        assert min(balances)>=0 and sum(balances)==4800 and 0<=amount<=15


def test_pity_probability_table_and_reward_specific_bases():
    import pytest
    assert [engine.treasure_success_chance(.35,n) for n in range(6)] == pytest.approx([.35,.45,.55,.65,.75,.75])
    assert engine.treasure_success_chance(.10,2)==pytest.approx(.30)


def test_boss_attack_gold_recovery_zero_and_defeat_once(game):
    app,ids,clients,connect=game
    from app.models.boss_rush import BossRushRoundConfig, BossRushBattleState
    from app.modes.boss_rush.engine import initialize_player_state, submit_current_answer, finalize_boss_rush_rewards
    with app.app_context():
        session=db.session.get(GameSession,ids['session']);session.mode='boss_rush'
        round_=GameRound.query.one()
        cfg=BossRushRoundConfig(shared_bank_enabled=False,attack_gold=10,round_id=round_.id,attack_problem_set_id=session.problem_set_id,
            recovery_problem_set_id=session.problem_set_id, boss_max_hp=10,ability_enabled=False)
        battle=BossRushBattleState(round_id=round_.id,current_boss_hp=10,status='active')
        db.session.add_all([cfg,battle]);db.session.flush()
        player=initialize_player_state(round_,ids['actor'],cfg)
        result=submit_current_answer(player,cfg,battle,submitted_text='4');assert result['is_correct']
        wallet=PlayerWallet.query.filter_by(player_id=ids['actor']).one();assert wallet.gold==10
        player.hp=0;player.current_problem_id=ids['problems'][1];player.current_problem_kind='recovery'
        assert submit_current_answer(player,cfg,battle,submitted_text='4')['is_correct']
        assert wallet.gold==10 and player.hp==1
        battle.is_defeated=True;battle.current_boss_hp=0
        assert finalize_boss_rush_rewards(session,round_,cfg,battle)['finalized']
        assert wallet.gold==35
        assert finalize_boss_rush_rewards(session,round_,cfg,battle)['already_finalized']
        assert wallet.gold==35
        session.status='finished';assert settle_session(session);db.session.commit()
        assert PlayerProgression.query.filter_by(player_id=ids['actor']).one().saved_gold==35


def test_ending_failed_boss_attempt_keeps_earned_gold(game):
    app,ids,clients,connect=game
    with app.app_context():
        session=db.session.get(GameSession,ids['session']);session.mode='boss_rush'
        db.session.add(PlayerWallet(session_id=session.id,player_id=ids['actor'],gold=40,gems=0));db.session.commit()
    assert clients['admin'].post(f'/admin/boss-rush/{ids["session"]}/end_session').status_code==302
    with app.app_context():assert PlayerProgression.query.filter_by(player_id=ids['actor']).one().saved_gold==40


def test_new_player_has_zero_saved_gold_and_reset_has_a_gold_ledger(game):
    app,ids,*_=game
    from app.models.player import Player
    from app.services.player_reset import reset_player_to_starting_state
    with app.app_context():
        player=db.session.get(Player,ids['actor'])
        reset_player_to_starting_state(player);db.session.commit()
        account=PlayerProgression.query.filter_by(player_id=player.id).one()
        assert account.saved_gold==account.diamonds_balance==0
        account.saved_gold=400;db.session.commit()
        reset_player_to_starting_state(player);db.session.commit()
        assert account.saved_gold==0 and GoldTransaction.query.one().amount_delta==-400
