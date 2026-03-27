# app/models/game.py
#
# Core game session models — mode-agnostic.
# These tables are shared by Classic, Team, and Boss Rush modes.
#
#   GameSession  — one "game" (a group of players playing together)
#   GameRound    — one question round inside a session
#   RoundPlayer  — which players are enrolled in a session
#   PlayerAnswer — a submitted answer from one player for one round

from datetime import datetime, timezone
from app.extensions import db


# ── GameSession ───────────────────────────────────────────────────────────────

class GameSession(db.Model):
    __tablename__ = 'game_session'

    id         = db.Column(db.Integer, primary_key=True)

    # mode: identifies which game mode this session uses.
    # Valid values: 'classic', 'team', 'boss_rush'
    mode       = db.Column(db.String(32), nullable=False)

    # status lifecycle: waiting → active → finished
    status     = db.Column(db.String(16), nullable=False, default='waiting')

    # Optional: link the session to a specific ProblemSet.
    # If None the problem engine selects problems by other criteria.
    problem_set_id = db.Column(db.Integer, db.ForeignKey('problem_set.id'), nullable=True)

    # G1: optional group restriction and custom label
    group_id = db.Column(db.Integer, db.ForeignKey('player_group.id'), nullable=True)
    label    = db.Column(db.String(128), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at   = db.Column(db.DateTime, nullable=True)

    # Relationships
    rounds         = db.relationship('GameRound',   backref='session', lazy='dynamic', cascade='all, delete-orphan')
    round_players  = db.relationship('RoundPlayer', backref='session', lazy='dynamic', cascade='all, delete-orphan')
    problem_set    = db.relationship('ProblemSet',  backref='sessions', lazy='select')
    group          = db.relationship('PlayerGroup', foreign_keys=[group_id])

    @property
    def display_label(self):
        if self.label:
            return self.label
        parts = []
        if self.problem_set:
            parts.append(self.problem_set.name)
        parts.append(self.group.name if self.group else 'Open')
        parts.append(self.created_at.strftime('%Y-%m-%d') if self.created_at else '')
        return ' — '.join(p for p in parts if p)

    def __repr__(self):
        return f'<GameSession id={self.id} mode={self.mode!r} status={self.status!r}>'


# ── GameRound ─────────────────────────────────────────────────────────────────

class GameRound(db.Model):
    __tablename__ = 'game_round'

    id           = db.Column(db.Integer, primary_key=True)
    session_id   = db.Column(db.Integer, db.ForeignKey('game_session.id'), nullable=False)
    # nullable=True: Classic mode rounds cover a whole problem set (no single problem);
    # other modes (Team, Boss Rush) will set this to a specific problem.
    problem_id   = db.Column(db.Integer, db.ForeignKey('problem.id'),      nullable=True)

    # round_number: 1-based index of this round within the session
    round_number      = db.Column(db.Integer,  nullable=False)
    time_limit_seconds = db.Column(db.Integer, nullable=True)   # None means no limit

    started_at = db.Column(db.DateTime, nullable=True)   # set by admin when round starts
    ended_at   = db.Column(db.DateTime, nullable=True)

    # Relationships
    problem = db.relationship('Problem',      backref='rounds',   lazy='select')
    answers = db.relationship('PlayerAnswer', backref='round',    lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<GameRound id={self.id} session={self.session_id} round={self.round_number}>'


# ── RoundPlayer ───────────────────────────────────────────────────────────────

class RoundPlayer(db.Model):
    __tablename__ = 'round_player'

    id         = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('game_session.id'), nullable=False)
    player_id  = db.Column(db.Integer, db.ForeignKey('player.id'),       nullable=False)

    # joined_at: when the player joined the session lobby
    joined_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Prevent the same player joining the same session twice
    __table_args__ = (
        db.UniqueConstraint('session_id', 'player_id', name='uq_round_player_session_player'),
    )

    player = db.relationship('Player', backref='round_players', lazy='select')

    def __repr__(self):
        return f'<RoundPlayer session={self.session_id} player={self.player_id}>'


# ── PlayerAnswer ──────────────────────────────────────────────────────────────

class PlayerAnswer(db.Model):
    __tablename__ = 'player_answer'

    id          = db.Column(db.Integer, primary_key=True)
    round_id    = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False)
    player_id   = db.Column(db.Integer, db.ForeignKey('player.id'),     nullable=False)

    answer_text = db.Column(db.String(512), nullable=False)

    # is_correct is set by problem_engine.check_answer() at submission time
    is_correct  = db.Column(db.Boolean, nullable=False, default=False)

    submitted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # A player can only submit one answer per round
    __table_args__ = (
        db.UniqueConstraint('round_id', 'player_id', name='uq_player_answer_round_player'),
    )

    player = db.relationship('Player', backref='answers', lazy='select')

    def __repr__(self):
        return f'<PlayerAnswer round={self.round_id} player={self.player_id} correct={self.is_correct}>'
