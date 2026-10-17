"""Admin-only persistent raster asset management."""

import os
import re
from uuid import uuid4

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.decorators import admin_required
from app.extensions import db
from app.models.gear import GearItemDefinition, GEAR_SLOT_TYPES, GEAR_SLOT_HEAD, GEAR_SLOT_CHEST
from app.models.media import UploadedAsset
from app.models.player import Player
from app.models.problems import ProblemBlock, ProblemChoiceOption
from app.services.uploaded_media import asset_url, remove_image, write_image
from app.services.avatar import list_available_face_keys


assets_bp = Blueprint('assets', __name__, url_prefix='/admin/assets')
_FACE_CATEGORIES = {'face_m': 'm', 'face_f': 'f'}
_GEAR_CATEGORIES = {'gear_layer', 'gear_icon'}
_ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}


def reference_count(asset):
    if asset.category in _FACE_CATEGORIES:
        return Player.query.filter_by(selected_face_key=asset.asset_key, avatar_body_variant=_FACE_CATEGORIES[asset.category]).count()
    if asset.category in _GEAR_CATEGORIES and asset.gear_item_id:
        return 1  # The Gear Catalog item is the reference.
    if asset.category == 'problem_image':
        return (ProblemBlock.query.filter_by(image_path=f'uploaded:{asset.id}').count() +
                ProblemChoiceOption.query.filter_by(image_asset_id=asset.id).count())
    return 0


def _validate_category():
    category = request.form.get('category')
    name = (request.form.get('display_name') or '').strip()
    if not name or len(name) > 128:
        raise ValueError('Display name must be 1–128 characters.')
    if category in _FACE_CATEGORIES:
        key = (request.form.get('asset_key') or '').strip() or ('u' + uuid4().hex[:10])
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,16}', key):
            raise ValueError('Face key must use 1–16 letters, numbers, underscores, or hyphens.')
        if key in list_available_face_keys(_FACE_CATEGORIES[category]):
            raise ValueError('That face key already exists. Use Replace on an uploaded asset instead.')
        return {'category': category, 'display_name': name, 'asset_key': key, 'variant': _FACE_CATEGORIES[category]}
    if category in _GEAR_CATEGORIES:
        item = db.session.get(GearItemDefinition, request.form.get('gear_item_id'))
        if item is None:
            raise ValueError('Select an existing Gear Catalog item.')
        variant = request.form.get('variant') or 'shared'
        if variant not in {'m', 'f', 'shared'}:
            raise ValueError('Invalid avatar variant.')
        layer = 'icon' if category == 'gear_icon' else request.form.get('layer')
        allowed_layers = {'front'}
        if item.slot_type == GEAR_SLOT_HEAD:
            allowed_layers.add('back')
        if item.slot_type == GEAR_SLOT_CHEST:
            allowed_layers.add('underlay')
        if category == 'gear_layer' and item.slot_type not in GEAR_SLOT_TYPES[:-1]:
            raise ValueError('This gear slot has no avatar layer; use a gear icon.')
        if layer not in ({'icon'} if category == 'gear_icon' else allowed_layers):
            raise ValueError('Invalid layer for this gear slot.')
        existing = UploadedAsset.query.filter_by(category=category, gear_item_id=item.id, variant=variant, layer=layer).first()
        if existing:
            raise ValueError('That item/variant/layer already has an uploaded image. Use Replace.')
        return {'category': category, 'display_name': name, 'gear_item_id': item.id, 'variant': variant, 'layer': layer}
    raise ValueError('Unsupported asset category.')


@assets_bp.route('/', methods=['GET', 'POST'])
@login_required
@admin_required
def index():
    if request.method == 'POST':
        try:
            fields = _validate_category()
            upload = request.files.get('image')
            if upload is None or os.path.splitext(upload.filename or '')[1].lower() not in _ALLOWED_EXTENSIONS:
                raise ValueError('Choose a PNG, JPEG, or WebP file.')
            saved = write_image(upload.read(16 * 1024 * 1024 + 1))
            asset = UploadedAsset(**fields, **{k: saved[k] for k in ('storage_name', 'media_type', 'sha256')})
            try:
                db.session.add(asset)
                db.session.commit()
            except Exception:
                db.session.rollback()
                remove_image(saved['storage_name'])
                raise
            flash('Asset uploaded.', 'success')
            return redirect(url_for('assets.index'))
        except ValueError as exc:
            flash(str(exc), 'error')
    assets = UploadedAsset.query.order_by(UploadedAsset.id.desc()).limit(200).all()
    rows = [{'asset': asset, 'url': asset_url(asset), 'references': reference_count(asset)} for asset in assets]
    gear_items = GearItemDefinition.query.order_by(GearItemDefinition.slot_type, GearItemDefinition.name).all()
    return render_template('admin/assets.html', rows=rows, gear_items=gear_items)


@assets_bp.route('/<int:asset_id>/replace', methods=['POST'])
@login_required
@admin_required
def replace(asset_id):
    asset = db.session.get(UploadedAsset, asset_id)
    if asset is None or asset.category == 'problem_image':
        flash('This asset cannot be replaced here.', 'error')
        return redirect(url_for('assets.index'))
    upload = request.files.get('image')
    try:
        if upload is None or os.path.splitext(upload.filename or '')[1].lower() not in _ALLOWED_EXTENSIONS:
            raise ValueError('Choose a PNG, JPEG, or WebP file.')
        saved = write_image(upload.read(16 * 1024 * 1024 + 1))
        old_names = [asset.storage_name, (asset.editor_state or {}).get('source_name')]
        asset.storage_name = saved['storage_name']
        asset.media_type = saved['media_type']
        asset.sha256 = saved['sha256']
        asset.editor_state = None
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            remove_image(saved['storage_name'])
            raise
        for name in old_names:
            if name:
                remove_image(name)
        flash('Asset replaced; its references remain attached.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('assets.index'))


@assets_bp.route('/<int:asset_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete(asset_id):
    asset = db.session.get(UploadedAsset, asset_id)
    if asset is None:
        flash('Asset not found.', 'error')
    elif asset.category == 'problem_image':
        flash('Imported problem images are managed by their source import and cannot be deleted here.', 'error')
    elif reference_count(asset) and request.form.get('confirm_referenced') != 'yes':
        flash('Asset is referenced. Tick the explicit confirmation box before deleting it.', 'error')
    else:
        names = [asset.storage_name, (asset.editor_state or {}).get('source_name')]
        db.session.delete(asset)
        db.session.commit()
        for name in names:
            if name:
                remove_image(name)
        flash('Uploaded asset deleted.', 'success')
    return redirect(url_for('assets.index'))
