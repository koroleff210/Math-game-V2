"""Public read-only delivery of validated raster images from persistent storage."""

import os
from flask import Blueprint, abort, current_app, send_from_directory
from app.extensions import db
from app.models.media import UploadedAsset


media_bp = Blueprint('media', __name__, url_prefix='/media')


@media_bp.route('/<int:asset_id>')
def file(asset_id):
    asset = db.session.get(UploadedAsset, asset_id)
    if asset is None or not os.path.isfile(os.path.join(current_app.config['MEDIA_ROOT'], asset.storage_name)):
        abort(404)
    response = send_from_directory(current_app.config['MEDIA_ROOT'], asset.storage_name, mimetype=asset.media_type, conditional=True)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
