"""Shared Boss Rush rewards: real answer/HTTP flows and exact payouts."""
from datetime import datetime, timezone
from pathlib import Path
import random, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from test_classic_realtime_delivery import game
from app.extensions import db
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.player import Player
from app.models.problems import Problem
from app.models.boss_rush import BossRushRoundConfig, BossRushBattleState, BossRushPlayerState, BossRushProblemAttempt
from app.models.classic import PlayerWallet
from app.models.progression import PlayerProgression, DiamondTransaction
from app.models.gear import GearItemDefinition, PlayerGearOwnership
from app.models.economy import GoldTransaction
from app.modes.boss_rush.engine import initialize_player_state, submit_current_answer, finalize_boss_rush_rewards, build_live_state_payload
from app.services.boss_rewards import attack_rewards, bank_shares, expire_bank
from app.services.economy import settle_session


@pytest.fixture
def boss(game):
    app,ids,clients,connect=game
    with app.app_context():
        session=db.session.get(GameSession,ids['session']);session.mode='boss_rush'
        for i in range(18):session.problem_set.problems.append(Problem(topic_id=session.problem_set.problems[0].topic_id,title=f'Attack {i}',prompt_text='2+2?',answer_text='4'))
        round_=GameRound.query.one()
        cfg=BossRushRoundConfig(round_id=round_.id,attack_problem_set_id=session.problem_set_id,
            recovery_problem_set_id=session.problem_set_id,boss_max_hp=100,ability_enabled=False)
        battle=BossRushBattleState(round_id=round_.id,current_boss_hp=100,status='active')
        db.session.add_all([cfg,battle]);db.session.flush()
        for role in ['actor','victim']:
            db.session.add(RoundPlayer(session_id=session.id,player_id=ids[role]))
            initialize_player_state(round_,ids[role],cfg)
        db.session.commit()
    return app,ids,clients


def world(ids):
    session=db.session.get(GameSession,ids['session']);round_=GameRound.query.filter_by(session_id=session.id).one()
    return session,round_,round_.boss_rush_config,round_.boss_rush_battle_state


def hit(ids,role='actor',correct=True):
    session,round_,cfg,battle=world(ids)
    player=BossRushPlayerState.query.filter_by(round_id=round_.id,player_id=ids[role]).one()
    result=submit_current_answer(player,cfg,battle,submitted_text='4' if correct else 'wrong')
    db.session.commit();return result


def test_combo_tiers_are_flat_and_recovery_awards_nothing(boss):
    app,ids,_=boss
    with app.app_context():
        session,round_,cfg,battle=world(ids)
        assert [attack_rewards(cfg,n) for n in [1,2,3,5,6,30]]==[(3,7),(3,7),(4,8),(4,8),(5,9),(5,9)]
        for _ in range(6):assert hit(ids)['is_correct']
        player=BossRushPlayerState.query.filter_by(player_id=ids['actor']).one()
        wallet=PlayerWallet.query.filter_by(player_id=ids['actor']).one()
        assert wallet.gold==23 and player.secured_gold==23 and battle.team_bank_gold==47
        assert battle.current_boss_hp==93 # sixth correct hit receives damage combo
        hit(ids,correct=False)
        assert player.current_combo==0 and wallet.gold==23 and battle.team_bank_gold==47
        player.hp=0;player.current_problem_kind='recovery';player.current_problem_id=round_.session.problem_set.problems[0].id
        assert hit(ids)['is_correct']
        assert wallet.gold==23 and battle.team_bank_gold==47
        assert sum(a.secured_gold_delta for a in BossRushProblemAttempt.query.all())==23
        assert sum(a.bank_gold_delta for a in BossRushProblemAttempt.query.all())==47


def test_exact_distribution_rewards_work_and_preserves_every_coin():
    assert bank_shares(29,{1:3,2:1,3:0})=={1:18,2:11}
    assert bank_shares(7,{1:1,2:1,3:1})=={1:3,2:2,3:2}
    rng=random.Random(17)
    for _ in range(1000):
        contributions={i:rng.randrange(21) for i in range(rng.randrange(1,31))}
        total=rng.randrange(5000)
        shares=bank_shares(total,contributions,rng.randrange(101))
        assert sum(shares.values())==(total if any(contributions.values()) else 0)
        assert all(n>=0 and contributions[pid]>0 for pid,n in shares.items())


def test_victory_auto_unlocks_all_players_and_banks_once(boss):
    app,ids,clients=boss
    with app.app_context():
        for _ in range(3):hit(ids)
        _,_,cfg,battle=world(ids);battle.current_boss_hp=1;db.session.commit()
        hit(ids,'victim')
        session,round_,cfg,battle=world(ids)
        assert battle.rewards_finalized_at and battle.team_bank_gold==29
        entries={e['player_id']:e for e in battle.final_rewards_json['entries']}
        assert entries[ids['actor']]['bank_share']==18 and entries[ids['victim']]['bank_share']==11
        assert PlayerWallet.query.filter_by(player_id=ids['actor']).one().gold==53
        assert PlayerWallet.query.filter_by(player_id=ids['victim']).one().gold==39
        assert finalize_boss_rush_rewards(session,round_,cfg,battle)['already_finalized']
        db.session.commit();db.session.expire_all()
        assert finalize_boss_rush_rewards(*world(ids))['already_finalized']
        payload=build_live_state_payload(*world(ids));assert payload['team_bank']['status']=='unlocked'
    for _ in range(2):assert clients['admin'].post(f'/admin/boss-rush/{ids["session"]}/end_session').status_code==302
    with app.app_context():
        assert PlayerProgression.query.filter_by(player_id=ids['actor']).one().saved_gold==53
        assert PlayerProgression.query.filter_by(player_id=ids['victim']).one().saved_gold==39
        assert GoldTransaction.query.count()==2


@pytest.mark.parametrize('end_path',['end','end_session'])
def test_failure_expires_bank_keeps_gold_and_rejects_late_answers(boss,end_path):
    app,ids,clients=boss
    with app.app_context():
        hit(ids);_,_,cfg,battle=world(ids);cfg.defeat_diamonds=2;db.session.commit()
    assert clients['admin'].post(f'/admin/boss-rush/{ids["session"]}/{end_path}').status_code==302
    with app.app_context():
        session,round_,cfg,battle=world(ids)
        assert battle.bank_expired_at and battle.team_bank_gold==7 and not battle.rewards_finalized_at
        assert PlayerWallet.query.filter_by(player_id=ids['actor']).one().gold==3
        assert DiamondTransaction.query.count()==0
        attempts=BossRushProblemAttempt.query.count()
        with pytest.raises(ValueError,match='expired'):finalize_boss_rush_rewards(session,round_,cfg,battle)
    clients['actor'].post(f'/boss-rush/game/{ids["session"]}/answer',data={'answer_text':'4'})
    page=clients['actor'].get(f'/boss-rush/lobby/{ids["session"]}',headers={'Sec-Fetch-Dest':'iframe'})
    assert b'expired' in page.data and b'Gold secured: 3' in page.data
    with app.app_context():assert BossRushProblemAttempt.query.count()==attempts


def test_recovery_only_or_idle_players_do_not_receive_victory_rewards(boss):
    app,ids,_=boss
    with app.app_context():
        _,round_,cfg,battle=world(ids)
        other=BossRushPlayerState.query.filter_by(player_id=ids['victim']).one();other.recovery_correct_count=1
        battle.current_boss_hp=1;cfg.defeat_diamonds=2;db.session.commit();hit(ids)
        entries={e['player_id']:e for e in battle.final_rewards_json['entries']}
        assert not entries[ids['victim']]['eligible'] and entries[ids['victim']]['total_gold']==0
        assert entries[ids['victim']]['total_diamonds']==0
        assert entries[ids['actor']]['bank_share']==7 and entries[ids['actor']]['total_diamonds']==2


@pytest.mark.parametrize('owned',[False,True])
def test_gear_and_diamond_loot_once_and_duplicate_alternative(boss,monkeypatch,owned):
    app,ids,_=boss;monkeypatch.setattr(random,'random',lambda:0.0)
    with app.app_context():
        session,round_,cfg,battle=world(ids)
        item=GearItemDefinition(id='victory_hat',name='Victory hat',slot_type='head',gold_cost=300)
        db.session.add(item);db.session.flush()
        if owned:db.session.add(PlayerGearOwnership(player_id=ids['actor'],item_id=item.id))
        cfg.defeat_gear_id=item.id;cfg.defeat_gear_chance=1;cfg.defeat_diamonds=2;battle.current_boss_hp=1
        db.session.commit();hit(ids)
        entry=next(e for e in battle.final_rewards_json['entries'] if e['player_id']==ids['actor'])
        assert entry['loot_received'] is (not owned)
        assert entry['loot_fallback_gold']==(150 if owned else 0)
        assert PlayerGearOwnership.query.filter_by(player_id=ids['actor'],item_id=item.id).count()==1
        assert PlayerProgression.query.filter_by(player_id=ids['actor']).one().diamonds_balance==2
        assert finalize_boss_rush_rewards(session,round_,cfg,battle)['already_finalized'];db.session.commit()
        assert DiamondTransaction.query.count()==1
        assert PlayerWallet.query.filter_by(player_id=ids['actor']).one().gold==(185 if owned else 35)


def test_failed_loot_roll_does_not_give_duplicate_compensation(boss,monkeypatch):
    app,ids,_=boss;monkeypatch.setattr(random,'random',lambda:.9)
    with app.app_context():
        _,_,cfg,battle=world(ids);cfg.defeat_gear_id='missing';cfg.defeat_gear_chance=.1;battle.current_boss_hp=1;db.session.commit();hit(ids)
        entry=next(e for e in battle.final_rewards_json['entries'] if e['player_id']==ids['actor'])
        assert not entry['loot_received'] and entry['loot_fallback_gold']==0


def test_round_reset_keeps_wallet_and_starts_empty_bank(boss):
    app,ids,_=boss
    with app.app_context():
        hit(ids);session,old,cfg,battle=world(ids);expire_bank(cfg,battle,session);old.ended_at=datetime.now(timezone.utc)
        new=GameRound(session_id=session.id,round_number=2,started_at=datetime.now(timezone.utc));db.session.add(new);db.session.flush()
        new_cfg=BossRushRoundConfig(round_id=new.id,attack_problem_set_id=session.problem_set_id,recovery_problem_set_id=session.problem_set_id)
        fresh=BossRushBattleState(round_id=new.id,current_boss_hp=30,status='active');db.session.add_all([new_cfg,fresh]);db.session.flush()
        player=initialize_player_state(new,ids['actor'],new_cfg);db.session.commit()
        assert player.current_combo==0 and fresh.team_bank_gold==0
        assert PlayerWallet.query.filter_by(player_id=ids['actor']).one().gold==3


def test_player_cannot_finalize_or_set_rewards(boss):
    app,ids,clients=boss
    assert clients['actor'].post(f'/admin/boss-rush/{ids["session"]}/finalize').status_code==403
    with app.app_context():assert not world(ids)[3].rewards_finalized_at


def test_admin_controls_and_player_counters_render(boss):
    app,ids,clients=boss
    admin=clients['admin'].get('/admin/boss-rush/new')
    assert b'bank_gold' in admin.data and b'defeat_gear_id' in admin.data and b'bank_equal_percent' in admin.data
    page=clients['actor'].get(f'/boss-rush/game/{ids["session"]}',headers={'Sec-Fetch-Dest':'iframe'})
    assert page.status_code==200 and b'Gold secured' in page.data and b'Team bank' in page.data
    assert b'data-next-secured' in page.data and b'window.location.reload()' in page.data


def test_legacy_player_keeps_hp_and_combo_without_new_reward_counters(boss):
    app,ids,clients=boss
    with app.app_context():
        world(ids)[0].economy_version=1;db.session.commit()
    from bs4 import BeautifulSoup
    page=clients['actor'].get(f'/boss-rush/game/{ids["session"]}',headers={'Sec-Fetch-Dest':'iframe'})
    soup=BeautifulSoup(page.data,'html.parser')
    assert soup.select_one('[data-player-combo]') and soup.select_one('[data-player-hearts]')
    assert not soup.select_one('[data-secured-gold]')
