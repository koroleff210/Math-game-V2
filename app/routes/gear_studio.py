"""Small admin-only editor; never changes player equipment or packaged art."""
import json
import re

from flask import Blueprint, abort, current_app, jsonify, render_template, request, send_from_directory
from flask_login import login_required

from app.decorators import admin_required
from app.extensions import db
from app.models.media import UploadedAsset
from app.services import gear_studio as studio

studio_bp = Blueprint('gear_studio', __name__, url_prefix='/admin/gear-studio')


@studio_bp.get('/')
@login_required
@admin_required
def index():
    return render_template('admin/gear/studio.html')


@studio_bp.get('/catalog')
@login_required
@admin_required
def catalog():
    response = jsonify(studio.catalog())
    response.headers['Cache-Control'] = 'no-store'
    return response


@studio_bp.get('/editor')
@login_required
@admin_required
def editor():
    try:
        response = jsonify(studio.editor_view(request.args.get('slot'), request.args.get('target'),
                                              request.args.get('variant'), request.args.get('layer')))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@studio_bp.get('/source/<int:asset_id>')
@login_required
@admin_required
def source(asset_id):
    asset = db.session.get(UploadedAsset, asset_id)
    filename = (asset.editor_state or {}).get('source_name') if asset else None
    if not re.fullmatch(r'[a-f0-9]{32}\.png', filename or ''):
        abort(404)
    response = send_from_directory(current_app.config['MEDIA_ROOT'], filename, mimetype='image/png')
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@studio_bp.post('/save')
@login_required
@admin_required
def save():
    try:
        upload = request.files.get('image')
        if upload is None:
            raise ValueError('Import a PNG before saving.')
        data = json.loads(request.form.get('metadata') or '{}')
        if not isinstance(data, dict):
            raise ValueError('Invalid editor details.')
        result = studio.save_element(data, upload.read(16 * 1024 * 1024 + 1))
        return jsonify(result)
    except studio.StudioConflict as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 409
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
