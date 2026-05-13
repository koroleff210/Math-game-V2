# app/models/boss_rush.py
#
# Boss Rush mode-specific persistence. These tables intentionally sit beside
# Classic runtime state instead of reusing Classic-only models.

from datetime import datetime, timezone

from app.extensions import db


BOSS_RUSH_STATUS_WAITING = 'waiting'
BOSS_RUSH_STATUS_ACTIVE = 'active'
BOSS_RUSH_STATUS_DEFEATED = 'defeated'
BOSS_RUSH_STATUS_ENDED = 'ended'

BOSS_RUSH_ATTEMPT_ATTACK = 'attack'
BOSS_RUSH_ATTEMPT_RECOVERY = 'recovery'


class BossRushRoundConfig(db.Model):
    __tablename__ = 'boss_rush_round_config'

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False, unique=True, index=True)

    boss_type = db.Column(db.String(64), nullable=False, default='fire_giant')
    boss_name = db.Column(db.String(128), nullable=True)
    boss_image_path = db.Column(db.String(255), nullable=True)
    boss_max_hp = db.Column(db.Integer, nullable=False, default=30)
    player_max_hp = db.Column(db.Integer, nullable=False, default=3)

    attack_problem_set_id = db.Column(db.Integer, db.ForeignKey('problem_set.id'), nullable=False)
    recovery_problem_set_id = db.Column(db.Integer, db.ForeignKey('problem_set.id'), nullable=False)

    first_place_diamonds = db.Column(db.Integer, nullable=False, default=5)
    second_place_diamonds = db.Column(db.Integer, nullable=False, default=4)
    third_place_diamonds = db.Column(db.Integer, nullable=False, default=3)
    other_participant_diamonds = db.Column(db.Integer, nullable=False, default=1)
    highest_combo_diamonds = db.Column(db.Integer, nullable=False, default=5)
    combo_bonus_threshold = db.Column(db.Integer, nullable=False, default=5)
    combo_bonus_damage = db.Column(db.Integer, nullable=False, default=1)
    ability_enabled = db.Column(db.Boolean, nullable=False, default=True)
    ability_interval_seconds = db.Column(db.Integer, nullable=False, default=60)
    fire_burn_damage = db.Column(db.Integer, nullable=False, default=1)
    fire_shield_max_stacks = db.Column(db.Integer, nullable=False, default=1)
    swamp_regen_amount = db.Column(db.Integer, nullable=False, default=2)
    stone_guard_combo_required = db.Column(db.Integer, nullable=False, default=3)
    time_drain_damage = db.Column(db.Integer, nullable=False, default=1)

    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    round = db.relationship('GameRound', backref=db.backref('boss_rush_config', uselist=False), lazy='select')
    attack_problem_set = db.relationship('ProblemSet', foreign_keys=[attack_problem_set_id], lazy='select')
    recovery_problem_set = db.relationship('ProblemSet', foreign_keys=[recovery_problem_set_id], lazy='select')


class BossRushBattleState(db.Model):
    __tablename__ = 'boss_rush_battle_state'

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False, unique=True, index=True)
    current_boss_hp = db.Column(db.Integer, nullable=False, default=30)
    status = db.Column(db.String(32), nullable=False, default=BOSS_RUSH_STATUS_WAITING)
    is_defeated = db.Column(db.Boolean, nullable=False, default=False)
    defeated_at = db.Column(db.DateTime, nullable=True)
    rewards_finalized_at = db.Column(db.DateTime, nullable=True)
    final_rewards_json = db.Column(db.JSON, nullable=True)
    next_ability_at = db.Column(db.DateTime, nullable=True)
    last_ability_at = db.Column(db.DateTime, nullable=True)
    ability_count = db.Column(db.Integer, nullable=False, default=0)
    ability_frozen = db.Column(db.Boolean, nullable=False, default=False)
    stone_guard_active = db.Column(db.Boolean, nullable=False, default=False)
    last_ability_summary_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    round = db.relationship('GameRound', backref=db.backref('boss_rush_battle_state', uselist=False), lazy='select')


class BossRushPlayerState(db.Model):
    __tablename__ = 'boss_rush_player_state'

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, index=True)

    hp = db.Column(db.Integer, nullable=False, default=3)
    damage_dealt = db.Column(db.Integer, nullable=False, default=0)
    current_combo = db.Column(db.Integer, nullable=False, default=0)
    max_combo = db.Column(db.Integer, nullable=False, default=0)
    correct_count = db.Column(db.Integer, nullable=False, default=0)
    incorrect_count = db.Column(db.Integer, nullable=False, default=0)
    recovery_correct_count = db.Column(db.Integer, nullable=False, default=0)
    recovery_incorrect_count = db.Column(db.Integer, nullable=False, default=0)
    is_observer = db.Column(db.Boolean, nullable=False, default=False)
    is_completed = db.Column(db.Boolean, nullable=False, default=False)
    current_problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'), nullable=True)
    current_problem_kind = db.Column(db.String(16), nullable=True)
    attack_never_ids = db.Column(db.JSON, nullable=True)
    attack_incorrect_ids = db.Column(db.JSON, nullable=True)
    attack_solved_ids = db.Column(db.JSON, nullable=True)
    recovery_never_ids = db.Column(db.JSON, nullable=True)
    recovery_incorrect_ids = db.Column(db.JSON, nullable=True)
    recovery_solved_ids = db.Column(db.JSON, nullable=True)
    last_contribution_at = db.Column(db.DateTime, nullable=True)
    fire_shield_stacks = db.Column(db.Integer, nullable=False, default=0)
    submitted_since_last_ability = db.Column(db.Boolean, nullable=False, default=True)
    last_ability_personal_message = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    round = db.relationship('GameRound', backref='boss_rush_player_states', lazy='select')
    player = db.relationship('Player', backref='boss_rush_states', lazy='select')
    current_problem = db.relationship('Problem', foreign_keys=[current_problem_id], lazy='select')

    __table_args__ = (
        db.UniqueConstraint('round_id', 'player_id', name='uq_boss_rush_player_round_player'),
    )


class BossRushProblemAttempt(db.Model):
    __tablename__ = 'boss_rush_problem_attempt'

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, index=True)
    problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'), nullable=False, index=True)
    attempt_type = db.Column(db.String(16), nullable=False)
    submitted_answer = db.Column(db.String(512), nullable=True)
    selected_option_id = db.Column(db.Integer, nullable=True)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    damage_dealt = db.Column(db.Integer, nullable=False, default=0)
    combo_before = db.Column(db.Integer, nullable=False, default=0)
    combo_after = db.Column(db.Integer, nullable=False, default=0)
    hp_before = db.Column(db.Integer, nullable=False, default=0)
    hp_after = db.Column(db.Integer, nullable=False, default=0)
    submitted_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    round = db.relationship('GameRound', backref='boss_rush_attempts', lazy='select')
    player = db.relationship('Player', backref='boss_rush_attempts', lazy='select')
    problem = db.relationship('Problem', backref='boss_rush_attempts', lazy='select')
