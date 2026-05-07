from datetime import datetime, timezone

from app.extensions import db


ANALYTICS_MODE_CLASSIC = 'classic'
ANALYTICS_MODE_BOSS_RUSH = 'boss_rush'

ANALYTICS_CONTEXT_CLASSIC = 'classic'
ANALYTICS_CONTEXT_BOSS_RUSH_ATTACK = 'boss_rush_attack'
ANALYTICS_CONTEXT_BOSS_RUSH_RECOVERY = 'boss_rush_recovery'

ANALYTICS_STATUS_UNSEEN = 'unseen'
ANALYTICS_STATUS_SEEN = 'seen'
ANALYTICS_STATUS_SOLVED = 'solved'
ANALYTICS_STATUS_INCORRECT = 'incorrect'
ANALYTICS_STATUS_CLOSED = 'closed'
ANALYTICS_STATUS_COMPLETED = 'completed'


def _utcnow():
    return datetime.now(timezone.utc)


class AnalyticsRound(db.Model):
    __tablename__ = 'analytics_round'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('game_session.id'), nullable=False, index=True)
    round_id = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False, unique=True, index=True)
    mode = db.Column(db.String(32), nullable=False, index=True)
    round_number = db.Column(db.Integer, nullable=True)
    session_label_snapshot = db.Column(db.String(255), nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey('player_group.id'), nullable=True, index=True)
    group_name_snapshot = db.Column(db.String(255), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True, index=True)
    subject_name_snapshot = db.Column(db.String(128), nullable=True)
    problem_set_id = db.Column(db.Integer, db.ForeignKey('problem_set.id'), nullable=True)
    problem_set_name_snapshot = db.Column(db.String(255), nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    finalized_at = db.Column(db.DateTime, nullable=True, index=True)
    round_settings_json = db.Column(db.JSON, nullable=True)
    mode_settings_json = db.Column(db.JSON, nullable=True)

    session = db.relationship('GameSession', lazy='select')
    round = db.relationship('GameRound', lazy='select')
    group = db.relationship('PlayerGroup', lazy='select')
    subject = db.relationship('Subject', lazy='select')
    problem_set = db.relationship('ProblemSet', lazy='select')


class AnalyticsRoundProblem(db.Model):
    __tablename__ = 'analytics_round_problem'

    id = db.Column(db.Integer, primary_key=True)
    analytics_round_id = db.Column(db.Integer, db.ForeignKey('analytics_round.id'), nullable=False, index=True)
    round_id = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False, index=True)
    problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'), nullable=False, index=True)
    problem_title_snapshot = db.Column(db.String(256), nullable=True)
    answer_type_snapshot = db.Column(db.String(32), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True)
    subject_name_snapshot = db.Column(db.String(128), nullable=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topic.id'), nullable=True)
    topic_name_snapshot = db.Column(db.String(128), nullable=True)
    mode_context = db.Column(db.String(64), nullable=False)
    problem_set_context = db.Column(db.JSON, nullable=True)
    source_metadata_json = db.Column(db.JSON, nullable=True)
    answer_key_snapshot_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    analytics_round = db.relationship('AnalyticsRound', backref=db.backref('round_problems', lazy='dynamic'), lazy='select')
    round = db.relationship('GameRound', lazy='select')
    problem = db.relationship('Problem', lazy='select')
    subject = db.relationship('Subject', lazy='select')
    topic = db.relationship('Topic', lazy='select')

    __table_args__ = (
        db.UniqueConstraint('round_id', 'problem_id', 'mode_context', name='uq_analytics_round_problem_context'),
    )


class AnalyticsPlayerRound(db.Model):
    __tablename__ = 'analytics_player_round'

    id = db.Column(db.Integer, primary_key=True)
    analytics_round_id = db.Column(db.Integer, db.ForeignKey('analytics_round.id'), nullable=False, index=True)
    round_id = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, index=True)
    player_name_snapshot = db.Column(db.String(80), nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey('player_group.id'), nullable=True)
    group_name_snapshot = db.Column(db.String(255), nullable=True)
    joined_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    finalized_at = db.Column(db.DateTime, nullable=True)

    problems_seen = db.Column(db.Integer, nullable=False, default=0)
    problems_attempted = db.Column(db.Integer, nullable=False, default=0)
    problems_solved = db.Column(db.Integer, nullable=False, default=0)
    correct_attempts = db.Column(db.Integer, nullable=False, default=0)
    incorrect_attempts = db.Column(db.Integer, nullable=False, default=0)
    first_try_correct_count = db.Column(db.Integer, nullable=False, default=0)
    accuracy = db.Column(db.Float, nullable=True)

    gold_start = db.Column(db.Integer, nullable=True)
    gold_end = db.Column(db.Integer, nullable=True)
    gems_start = db.Column(db.Integer, nullable=True)
    gems_end = db.Column(db.Integer, nullable=True)
    gold_net = db.Column(db.Integer, nullable=True)
    gems_net = db.Column(db.Integer, nullable=True)

    damage_dealt = db.Column(db.Integer, nullable=False, default=0)
    max_combo = db.Column(db.Integer, nullable=False, default=0)
    final_combo = db.Column(db.Integer, nullable=False, default=0)
    hp_final = db.Column(db.Integer, nullable=True)
    attack_correct = db.Column(db.Integer, nullable=False, default=0)
    attack_incorrect = db.Column(db.Integer, nullable=False, default=0)
    recovery_correct = db.Column(db.Integer, nullable=False, default=0)
    recovery_incorrect = db.Column(db.Integer, nullable=False, default=0)
    boss_rank = db.Column(db.Integer, nullable=True)
    diamonds_awarded = db.Column(db.Integer, nullable=False, default=0)
    summary_json = db.Column(db.JSON, nullable=True)

    analytics_round = db.relationship('AnalyticsRound', backref=db.backref('player_rounds', lazy='dynamic'), lazy='select')
    round = db.relationship('GameRound', lazy='select')
    player = db.relationship('Player', lazy='select')
    group = db.relationship('PlayerGroup', lazy='select')

    __table_args__ = (
        db.UniqueConstraint('round_id', 'player_id', name='uq_analytics_player_round_player'),
    )


class AnalyticsPlayerProblem(db.Model):
    __tablename__ = 'analytics_player_problem'

    id = db.Column(db.Integer, primary_key=True)
    analytics_round_id = db.Column(db.Integer, db.ForeignKey('analytics_round.id'), nullable=False, index=True)
    round_id = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, index=True)
    problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'), nullable=False, index=True)
    mode_context = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(32), nullable=False, default=ANALYTICS_STATUS_UNSEEN)
    first_seen_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    first_attempt_correct = db.Column(db.Boolean, nullable=True)
    eventual_correct = db.Column(db.Boolean, nullable=True)
    problem_title_snapshot = db.Column(db.String(256), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True)
    subject_name_snapshot = db.Column(db.String(128), nullable=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topic.id'), nullable=True)
    topic_name_snapshot = db.Column(db.String(128), nullable=True)
    source_metadata_json = db.Column(db.JSON, nullable=True)
    extra_json = db.Column(db.JSON, nullable=True)

    analytics_round = db.relationship('AnalyticsRound', backref=db.backref('player_problems', lazy='dynamic'), lazy='select')
    round = db.relationship('GameRound', lazy='select')
    player = db.relationship('Player', lazy='select')
    problem = db.relationship('Problem', lazy='select')
    subject = db.relationship('Subject', lazy='select')
    topic = db.relationship('Topic', lazy='select')

    __table_args__ = (
        db.UniqueConstraint('round_id', 'player_id', 'problem_id', 'mode_context', name='uq_analytics_player_problem_context'),
    )


class AnalyticsAnswerAttempt(db.Model):
    __tablename__ = 'analytics_answer_attempt'

    id = db.Column(db.Integer, primary_key=True)
    analytics_player_problem_id = db.Column(db.Integer, db.ForeignKey('analytics_player_problem.id'), nullable=True, index=True)
    analytics_round_id = db.Column(db.Integer, db.ForeignKey('analytics_round.id'), nullable=False, index=True)
    round_id = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, index=True)
    problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'), nullable=False, index=True)
    attempt_number = db.Column(db.Integer, nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    submitted_answer_text = db.Column(db.Text, nullable=True)
    selected_option_id = db.Column(db.Integer, nullable=True, index=True)
    selected_option_label_snapshot = db.Column(db.String(16), nullable=True)
    selected_option_text_snapshot = db.Column(db.Text, nullable=True)
    is_correct = db.Column(db.Boolean, nullable=False)
    mode_context = db.Column(db.String(64), nullable=False)
    action_context = db.Column(db.String(64), nullable=True)
    extra_json = db.Column(db.JSON, nullable=True)

    analytics_player_problem = db.relationship('AnalyticsPlayerProblem', backref=db.backref('answer_attempts', lazy='dynamic'), lazy='select')
    analytics_round = db.relationship('AnalyticsRound', backref=db.backref('answer_attempts', lazy='dynamic'), lazy='select')
    round = db.relationship('GameRound', lazy='select')
    player = db.relationship('Player', lazy='select')
    problem = db.relationship('Problem', lazy='select')

    __table_args__ = (
        db.UniqueConstraint('round_id', 'player_id', 'problem_id', 'mode_context', 'attempt_number', name='uq_analytics_answer_attempt_number'),
        db.Index('ix_analytics_answer_round_submitted', 'round_id', 'submitted_at'),
        db.Index('ix_analytics_answer_player_submitted', 'player_id', 'submitted_at'),
        db.Index('ix_analytics_answer_problem_correct', 'problem_id', 'is_correct'),
    )


class AnalyticsClassicEconomyEvent(db.Model):
    __tablename__ = 'analytics_classic_economy_event'

    id = db.Column(db.Integer, primary_key=True)
    analytics_round_id = db.Column(db.Integer, db.ForeignKey('analytics_round.id'), nullable=False, index=True)
    round_id = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey('game_session.id'), nullable=True, index=True)
    event_type = db.Column(db.String(64), nullable=False, index=True)
    event_key = db.Column(db.String(255), nullable=True, unique=True)
    occurred_at = db.Column(db.DateTime, nullable=False, default=_utcnow, index=True)
    actor_player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, index=True)
    actor_name_snapshot = db.Column(db.String(80), nullable=True)
    target_player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True, index=True)
    target_name_snapshot = db.Column(db.String(80), nullable=True)
    linked_answer_attempt_id = db.Column(db.Integer, db.ForeignKey('analytics_answer_attempt.id'), nullable=True)
    linked_problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'), nullable=True)
    action_context = db.Column(db.String(64), nullable=True)
    gold_delta_actor = db.Column(db.Integer, nullable=False, default=0)
    gold_delta_target = db.Column(db.Integer, nullable=False, default=0)
    gems_delta_actor = db.Column(db.Integer, nullable=False, default=0)
    gems_delta_target = db.Column(db.Integer, nullable=False, default=0)
    actor_gold_after = db.Column(db.Integer, nullable=True)
    target_gold_after = db.Column(db.Integer, nullable=True)
    item_key = db.Column(db.String(128), nullable=True)
    bonus_key = db.Column(db.String(128), nullable=True)
    problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'), nullable=True)
    details_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    analytics_round = db.relationship('AnalyticsRound', backref=db.backref('classic_economy_events', lazy='dynamic'), lazy='select')
    round = db.relationship('GameRound', lazy='select')
    session = db.relationship('GameSession', lazy='select')
    actor = db.relationship('Player', foreign_keys=[actor_player_id], lazy='select')
    target = db.relationship('Player', foreign_keys=[target_player_id], lazy='select')
    linked_answer_attempt = db.relationship('AnalyticsAnswerAttempt', lazy='select')
    linked_problem = db.relationship('Problem', foreign_keys=[linked_problem_id], lazy='select')
    problem = db.relationship('Problem', foreign_keys=[problem_id], lazy='select')


class AnalyticsBossRushBattleEvent(db.Model):
    __tablename__ = 'analytics_boss_rush_battle_event'

    id = db.Column(db.Integer, primary_key=True)
    analytics_round_id = db.Column(db.Integer, db.ForeignKey('analytics_round.id'), nullable=False, index=True)
    round_id = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey('game_session.id'), nullable=True, index=True)
    event_type = db.Column(db.String(64), nullable=False, index=True)
    occurred_at = db.Column(db.DateTime, nullable=False, default=_utcnow, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True, index=True)
    player_name_snapshot = db.Column(db.String(80), nullable=True)
    target_player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    target_player_name_snapshot = db.Column(db.String(80), nullable=True)
    linked_answer_attempt_id = db.Column(db.Integer, db.ForeignKey('analytics_answer_attempt.id'), nullable=True)
    linked_boss_rush_attempt_id = db.Column(db.Integer, db.ForeignKey('boss_rush_problem_attempt.id'), nullable=True)
    linked_problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'), nullable=True)
    boss_type = db.Column(db.String(64), nullable=True)
    boss_hp_before = db.Column(db.Integer, nullable=True)
    boss_hp_after = db.Column(db.Integer, nullable=True)
    player_hp_before = db.Column(db.Integer, nullable=True)
    player_hp_after = db.Column(db.Integer, nullable=True)
    combo_before = db.Column(db.Integer, nullable=True)
    combo_after = db.Column(db.Integer, nullable=True)
    damage_intended = db.Column(db.Integer, nullable=False, default=0)
    damage_applied = db.Column(db.Integer, nullable=False, default=0)
    shield_or_guard_absorbed = db.Column(db.Integer, nullable=False, default=0)
    ability_key = db.Column(db.String(64), nullable=True, index=True)
    ability_count = db.Column(db.Integer, nullable=True)
    details_json = db.Column(db.JSON, nullable=True)
    event_key = db.Column(db.String(255), nullable=True, unique=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    analytics_round = db.relationship('AnalyticsRound', backref=db.backref('boss_rush_battle_events', lazy='dynamic'), lazy='select')
    round = db.relationship('GameRound', lazy='select')
    session = db.relationship('GameSession', lazy='select')
    player = db.relationship('Player', foreign_keys=[player_id], lazy='select')
    target_player = db.relationship('Player', foreign_keys=[target_player_id], lazy='select')
    linked_answer_attempt = db.relationship('AnalyticsAnswerAttempt', lazy='select')
    linked_boss_rush_attempt = db.relationship('BossRushProblemAttempt', lazy='select')
    linked_problem = db.relationship('Problem', lazy='select')
