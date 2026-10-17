"""Validate and resolve persistent raster uploads without touching app/static."""

from io import BytesIO
import hashlib
import os
import re
from uuid import uuid4

from flask import current_app, url_for
from PIL import Image, UnidentifiedImageError

from app.models.media import UploadedAsset
from app.extensions import db


_FORMATS = {'PNG': ('png', 'image/png'), 'JPEG': ('jpg', 'image/jpeg'), 'WEBP': ('webp', 'image/webp')}
_STORAGE_NAME = re.compile(r'^[a-f0-9]{32}\.(?:png|jpg|webp)$')


def media_root():
    root = current_app.config['MEDIA_ROOT']
    os.makedirs(root, exist_ok=True)
    return root


def validate_image(data: bytes):
    if not data or len(data) > 16 * 1024 * 1024:
        raise ValueError('Image must be between 1 byte and 16 MiB.')
    try:
        with Image.open(BytesIO(data)) as probe:
            image_format = probe.format
            if image_format not in _FORMATS or probe.width > 10000 or probe.height > 10000 or probe.width * probe.height > 40_000_000:
                raise ValueError('Only PNG, JPEG, or WebP images up to 40 megapixels are supported.')
            probe.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
            clean = BytesIO()
            image.save(clean, format=image_format)
            cleaned = clean.getvalue()
            return cleaned, _FORMATS[image_format][0], _FORMATS[image_format][1], image.width, image.height
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError('Uploaded file is not a valid PNG, JPEG, or WebP image.') from exc


def write_image(data: bytes):
    cleaned, extension, media_type, width, height = validate_image(data)
    name = f'{uuid4().hex}.{extension}'
    path = os.path.join(media_root(), name)
    with open(path, 'xb') as handle:
        handle.write(cleaned)
    return {'storage_name': name, 'media_type': media_type, 'sha256': hashlib.sha256(cleaned).hexdigest(), 'width': width, 'height': height}


def remove_image(name):
    if _STORAGE_NAME.fullmatch(name or ''):
        try:
            os.unlink(os.path.join(media_root(), name))
        except FileNotFoundError:
            pass


def asset_url(asset):
    return url_for('media.file', asset_id=asset.id) if asset else None


def resolve_problem_image_url(path):
    if (path or '').startswith('uploaded:'):
        try:
            asset_id = int(path.split(':', 1)[1])
        except ValueError:
            return ''
        return asset_url(db.session.get(UploadedAsset, asset_id)) or ''
    return url_for('static', filename=path or '')


def find_gear_asset(item_id, variant, layer, category='gear_layer'):
    if not item_id:
        return None
    return (UploadedAsset.query.filter_by(category=category, gear_item_id=item_id, variant=variant, layer=layer).first()
            or UploadedAsset.query.filter_by(category=category, gear_item_id=item_id, variant='shared', layer=layer).first())
