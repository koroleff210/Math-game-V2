# app/models/groups.py
#
# PlayerGroup model — named groups of players used to restrict Classic Mode sessions.
# Association table player_group_members handles many-to-many Player ↔ PlayerGroup.

from datetime import datetime, timezone
from app.extensions import db

player_group_members = db.Table(
    'player_group_members',
    db.Column('player_id', db.Integer, db.ForeignKey('player.id'), primary_key=True),
    db.Column('group_id',  db.Integer, db.ForeignKey('player_group.id'), primary_key=True),
)


class PlayerGroup(db.Model):
    __tablename__ = 'player_group'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(64), nullable=False, unique=True)
    description = db.Column(db.String(256), nullable=True)
    created_at  = db.Column(db.DateTime, nullable=False,
                            default=lambda: datetime.now(timezone.utc))

    members = db.relationship('Player', secondary=player_group_members,
                              backref='groups', lazy='dynamic')

    def __repr__(self):
        return f'<PlayerGroup {self.name!r}>'
