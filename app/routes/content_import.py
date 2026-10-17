"""Admin-only, two-step Questionbank v4 import."""

import hashlib
import os
from uuid import uuid4

from flask import Blueprint, current_app, flash, render_template, request, session
from flask_login import login_required

from app.decorators import admin_required
from app.extensions import db
from app.models.subjects import Subject
from app.services.v4_import import ArchiveError, inspect_archive, apply_import, stage_path


import_bp = Blueprint('content_import', __name__, url_prefix='/admin/content-import')


@import_bp.route('/', methods=['GET', 'POST'])
@login_required
@admin_required
def index():
    report = None
    result = None
    stage = session.get('v4_import_stage')
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'validate':
            upload = request.files.get('archive')
            subject_id = request.form.get('subject_id', type=int)
            new_subject = (request.form.get('new_subject') or '').strip()
            subject = db.session.get(Subject, subject_id) if subject_id else None
            subject_name = new_subject or (subject.name if subject else 'Physics')
            if len(subject_name) > 64 or not subject_name:
                flash('Subject name must be 1–64 characters.', 'error')
            elif upload is None or not (upload.filename or '').lower().endswith('.zip'):
                flash('Choose a Questionbank v4 ZIP file.', 'error')
            else:
                stage_id = uuid4().hex
                path = stage_path(stage_id)
                try:
                    upload.save(path)
                    report = inspect_archive(path)
                    with open(path, 'rb') as handle:
                        digest = hashlib.sha256(handle.read()).hexdigest()
                    if stage:
                        old_path = stage_path(stage['id'])
                        if os.path.exists(old_path):
                            os.unlink(old_path)
                    session['v4_import_stage'] = {'id': stage_id, 'sha256': digest, 'subject_name': subject_name}
                    stage = session['v4_import_stage']
                except (ValueError, ArchiveError) as exc:
                    if os.path.exists(path):
                        os.unlink(path)
                    flash(str(exc), 'error')
        elif action == 'import':
            if not stage or request.form.get('stage_id') != stage.get('id'):
                flash('Import preview expired. Validate the ZIP again.', 'error')
            else:
                path = stage_path(stage['id'])
                try:
                    with open(path, 'rb') as handle:
                        digest = hashlib.sha256(handle.read()).hexdigest()
                    if digest != stage['sha256']:
                        raise ArchiveError('Staged ZIP changed; validate it again.')
                    result = apply_import(path, stage['subject_name'])
                    os.unlink(path)
                    session.pop('v4_import_stage', None)
                    stage = None
                    flash('Import committed successfully.', 'success')
                except (OSError, ValueError, ArchiveError) as exc:
                    flash(f'Import failed; database was rolled back: {exc}', 'error')
                except Exception:
                    current_app.logger.exception('Questionbank v4 import failed')
                    flash('Import failed unexpectedly; database was rolled back. Check server logs.', 'error')
        else:
            flash('Unknown import action.', 'error')
    if stage and report is None:
        try:
            report = inspect_archive(stage_path(stage['id']))
        except (OSError, ValueError):
            session.pop('v4_import_stage', None)
            stage = None
    return render_template('admin/content_import.html', subjects=Subject.query.order_by(Subject.name).all(),
                           stage=stage, report=report, result=result)
