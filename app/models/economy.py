"""Permanent gold audit trail. Diamonds have their own ledger."""
from datetime import datetime, timezone
from app.extensions import db


class GoldTransaction(db.Model):
    __tablename__ = 'gold_transaction'
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('game_session.id'), nullable=True)
    event_key = db.Column(db.String(160), nullable=False, unique=True)
    amount_delta = db.Column(db.Integer, nullable=False)
    balance_after = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
