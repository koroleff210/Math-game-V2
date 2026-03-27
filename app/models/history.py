# app/models/history.py
#
# Round history models — mode-agnostic frozen snapshots.
#
# History unit = finished round (NOT session).
# Session is only the container; multiple rounds may occur within one session.
#
#   RoundHistory       — one frozen record per finished round
#   RoundPlayerResult  — one frozen record per player per finished round
#
# These records are created once at round-end (by freeze_round_history in
# app/modes/classic/history_snapshot.py) and NEVER mutated afterwards.
# Later carry-over resets, store purchases, or next-round actions cannot
# affect records already written here.
#
# Idempotency is enforced by the UNIQUE constraint on RoundHistory.round_id.

import csv
import io

from app.extensions import db


# ── RoundHistory ──────────────────────────────────────────────────────────────

class RoundHistory(db.Model):
    """Frozen aggregate snapshot of one finished round.

    Created once at round-end.  Never mutated after creation.
    round_id has a UNIQUE constraint — used as the idempotency key.
    """
    __tablename__ = 'round_history'

    id         = db.Column(db.Integer, primary_key=True)
    round_id   = db.Column(db.Integer, db.ForeignKey('game_round.id'),   unique=True, nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('game_session.id'), nullable=False)

    # Mode type — extensible for classic / team / boss_rush
    mode_type    = db.Column(db.String(32), nullable=False)
    round_number = db.Column(db.Integer, nullable=False)

    # Frozen context snapshots
    # problem_set_id and group_id are stored as plain integers (no FK) so that
    # deleting a problem set or group never destroys historical records.
    session_label_snapshot    = db.Column(db.String(256), nullable=True)
    problem_set_id            = db.Column(db.Integer,     nullable=True)
    problem_set_name_snapshot = db.Column(db.String(128), nullable=True)
    group_id                  = db.Column(db.Integer,     nullable=True)
    group_name_snapshot       = db.Column(db.String(128), nullable=True)  # NULL = open session

    # Timestamps (started_at may be None if round was ended before being started)
    started_at  = db.Column(db.DateTime, nullable=True)
    ended_at    = db.Column(db.DateTime, nullable=False)

    # Archive state — NULL means active; non-NULL means archived (records the archival time)
    # Archived records are hidden from default H1/H2a views but retained in the database.
    archived_at = db.Column(db.DateTime, nullable=True, default=None)

    # Frozen round aggregate totals
    player_count     = db.Column(db.Integer, nullable=False, default=0)
    total_answers    = db.Column(db.Integer, nullable=False, default=0)
    total_correct    = db.Column(db.Integer, nullable=False, default=0)
    total_incorrect  = db.Column(db.Integer, nullable=False, default=0)
    overall_accuracy = db.Column(db.Float,   nullable=False, default=0.0)

    # Relationships
    round          = db.relationship('GameRound',         backref=db.backref('history', uselist=False))
    session        = db.relationship('GameSession',        backref='round_histories')
    player_results = db.relationship(
        'RoundPlayerResult', backref='round_history',
        cascade='all, delete-orphan', lazy='dynamic',
    )

    def __repr__(self):
        return (
            f'<RoundHistory round={self.round_id} session={self.session_id} '
            f'mode={self.mode_type!r} round_number={self.round_number}>'
        )


# ── RoundPlayerResult ─────────────────────────────────────────────────────────

class RoundPlayerResult(db.Model):
    """Frozen snapshot of one player's results in one finished round.

    Created once at round-end alongside RoundHistory.
    Never mutated after creation.

    Statistics definitions:
      total_answers  = sum of PlayerProblemState.attempts_used for this player/round
      correct        = count of PlayerProblemState rows where is_solved=True
      incorrect      = total_answers - correct
      accuracy       = correct / total_answers  (0.0 if total_answers == 0)
      final_gold     = PlayerWallet.gold at the moment end_round was called
                       (before any carry-over resets in the next_round flow)
      final_gems     = PlayerWallet.gems at the same moment
      final_place    = 1-based competition rank by gold (ties share the same rank)
    """
    __tablename__ = 'round_player_result'

    id               = db.Column(db.Integer, primary_key=True)
    round_history_id = db.Column(db.Integer, db.ForeignKey('round_history.id'), nullable=False)
    player_id        = db.Column(db.Integer, db.ForeignKey('player.id'),        nullable=False)

    # Frozen player identity — preserved even if the player account is renamed
    player_name_snapshot = db.Column(db.String(64), nullable=False)

    # Frozen leaderboard and economy results
    final_place = db.Column(db.Integer, nullable=False)
    final_gold  = db.Column(db.Integer, nullable=False)
    final_gems  = db.Column(db.Integer, nullable=False, default=0)

    # Frozen per-player answer statistics
    total_answers = db.Column(db.Integer, nullable=False, default=0)
    correct       = db.Column(db.Integer, nullable=False, default=0)
    incorrect     = db.Column(db.Integer, nullable=False, default=0)
    accuracy      = db.Column(db.Float,   nullable=False, default=0.0)

    __table_args__ = (
        db.UniqueConstraint(
            'round_history_id', 'player_id',
            name='uq_rpr_history_player',
        ),
    )

    player = db.relationship('Player', backref='round_results', lazy='select')

    def __repr__(self):
        return (
            f'<RoundPlayerResult history={self.round_history_id} '
            f'player={self.player_id} place={self.final_place} gold={self.final_gold}>'
        )


# ── CSV export helper ─────────────────────────────────────────────────────────

_CSV_HEADERS = [
    'session_id', 'session_label_snapshot', 'round_history_id', 'round_number',
    'mode_type', 'ended_at', 'problem_set_name_snapshot', 'group_name_snapshot',
    'player_count', 'round_total_answers', 'round_total_correct', 'round_total_incorrect',
    'round_overall_accuracy', 'player_id', 'player_name_snapshot',
    'final_place', 'final_gold', 'final_gems',
    'player_total_answers', 'player_correct', 'player_incorrect', 'player_accuracy',
    'archived_status',
]


def build_history_csv(rounds):
    """Return a UTF-8 CSV string — one row per player per frozen round.

    Reads only from RoundHistory and RoundPlayerResult (frozen data).
    If a round has no player results, one summary row is written with empty
    player columns.  If *rounds* is empty, returns a headers-only CSV.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_CSV_HEADERS)
    for rh in rounds:
        results = (
            RoundPlayerResult.query
            .filter_by(round_history_id=rh.id)
            .order_by(RoundPlayerResult.final_place, RoundPlayerResult.player_name_snapshot)
            .all()
        )
        archived_status = 'archived' if rh.archived_at else 'active'
        round_prefix = [
            rh.session_id,
            rh.session_label_snapshot or '',
            rh.id,
            rh.round_number,
            rh.mode_type,
            rh.ended_at.strftime('%Y-%m-%dT%H:%M:%S'),
            rh.problem_set_name_snapshot or '',
            rh.group_name_snapshot or '',
            rh.player_count,
            rh.total_answers,
            rh.total_correct,
            rh.total_incorrect,
            round(rh.overall_accuracy, 4),
        ]
        if results:
            for r in results:
                writer.writerow(round_prefix + [
                    r.player_id,
                    r.player_name_snapshot,
                    r.final_place,
                    r.final_gold,
                    r.final_gems,
                    r.total_answers,
                    r.correct,
                    r.incorrect,
                    round(r.accuracy, 4),
                    archived_status,
                ])
        else:
            # Round with no player results — write one summary row, empty player columns
            writer.writerow(round_prefix + ['', '', '', '', '', '', '', '', '', archived_status])
    return output.getvalue()
