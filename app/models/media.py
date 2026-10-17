"""Persistent uploaded media metadata; image bytes live in GAME_MEDIA_ROOT."""

from datetime import datetime, timezone

from app.extensions import db


class UploadedAsset(db.Model):
    __tablename__ = 'uploaded_asset'

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(32), nullable=False, index=True)
    display_name = db.Column(db.String(128), nullable=False)
    asset_key = db.Column(db.String(64), nullable=True, index=True)
    gear_item_id = db.Column(db.String(64), db.ForeignKey('gear_item_definition.id'), nullable=True, index=True)
    variant = db.Column(db.String(8), nullable=True)
    layer = db.Column(db.String(16), nullable=True)
    storage_name = db.Column(db.String(96), nullable=False, unique=True)
    media_type = db.Column(db.String(32), nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    editor_state = db.Column(db.JSON, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    gear_item = db.relationship('GearItemDefinition', backref='uploaded_assets')
