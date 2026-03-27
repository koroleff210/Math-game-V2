# app/models/subjects.py
#
# Subject model — broad area that groups Topics.
# Hierarchy: Subject → Topic → Problem

from datetime import datetime, timezone
from app.extensions import db


class Subject(db.Model):
    __tablename__ = 'subject'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(64), nullable=False, unique=True)
    description = db.Column(db.String(256), nullable=True)
    created_at  = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # One Subject has many Topics.
    topics = db.relationship('Topic', backref='subject_obj', lazy='dynamic')

    def __repr__(self):
        return f'<Subject {self.name!r}>'
