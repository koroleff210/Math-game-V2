"""Teacher session reports and publication-gated student review."""
from datetime import datetime, timezone
from copy import deepcopy
from hashlib import sha256

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_, select

from app.decorators import admin_required
from app.extensions import db
from app.models.analytics import AnalyticsRound, AnalyticsRoundProblem, AnalyticsSessionSettings
from app.models.game import GameSession, RoundPlayer
from app.models.groups import PlayerGroup
from app.services.learning_exports import evidence_zip
from app.services.learning_reports import build_session_report, ensure_session_settings, student_session_ids
from app.services.learning_snapshots import ASSET_NAME, asset_directory, snapshot_assets

learning_bp = Blueprint('learning', __name__)
CONTEXTS = ('classic', 'boss_rush_attack', 'boss_rush_recovery')


@learning_bp.after_request
def private_reports(response):
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def _session(session_id, *, student=False):
    session = db.session.get(GameSession, session_id)
    if session is None:
        abort(404)
    if student and not db.session.scalar(select(GameSession.id).where(GameSession.id == session_id, GameSession.id.in_(student_session_ids(current_user.id)))):
        abort(404)
    return session


def _scope():
    context = request.args.get('context') or None
    if context and context not in CONTEXTS:
        abort(400)
    numbers = {}
    for name in ('student', 'round'):
        raw = request.args.get(name)
        if raw and (not raw.isdecimal() or int(raw) < 1):
            abort(400, 'Student and round IDs must be positive integers.')
        numbers[name] = int(raw) if raw else None
    return dict(player_id=numbers['student'], round_id=numbers['round'], mode_context=context)


@learning_bp.get('/admin/analytics/sessions')
@login_required
@admin_required
def sessions():
    q = GameSession.query
    term = (request.args.get('q') or '').strip()[:128]
    group = request.args.get('group', type=int)
    mode = request.args.get('mode')
    student = request.args.get('student', type=int)
    if term:
        q = q.filter(GameSession.label.ilike('%' + term.replace('%', '\\%').replace('_', '\\_') + '%', escape='\\'))
    if group:
        q = q.filter_by(group_id=group)
    if mode in ('classic', 'boss_rush'):
        q = q.filter_by(mode=mode)
    if student:
        q = q.filter(GameSession.id.in_(select(RoundPlayer.session_id).where(RoundPlayer.player_id == student)))
    from app.services.analytics_reports import parse_date_filter
    for field, end in [('date_from', False), ('date_to', True)]:
        value = request.args.get(field)
        boundary = parse_date_filter(value, end=end)
        if value and boundary is None:
            abort(400, 'Use YYYY-MM-DD for date filters.')
        if boundary:
            q = q.filter(GameSession.created_at <= boundary if end else GameSession.created_at >= boundary)
    page = q.order_by(GameSession.created_at.desc(), GameSession.id.desc()).paginate(page=request.args.get('page', 1, type=int), per_page=20, error_out=False)
    reports = [build_session_report(s, player_id=student) for s in page.items]
    return render_template('admin/analytics/sessions.html', reports=reports, pagination=page,
                           groups=PlayerGroup.query.order_by(PlayerGroup.name).all())


@learning_bp.get('/admin/analytics/sessions/<int:session_id>')
@login_required
@admin_required
def session_detail(session_id):
    session = _session(session_id)
    scope = _scope()
    full = build_session_report(session)
    report = build_session_report(session, **scope) if any(v is not None for v in scope.values()) else full
    return render_template('admin/analytics/session_detail.html', report=report, student_choices=full['students'], student_view=False)


@learning_bp.post('/admin/analytics/sessions/<int:session_id>/settings')
@login_required
@admin_required
def settings(session_id):
    session = _session(session_id)
    report = build_session_report(session)
    settings = ensure_session_settings(session)
    action = request.form.get('action')
    if action == 'publish':
        if session.status != 'finished' or not report['finalized']:
            abort(400, 'Finish the session and all rounds before publishing results.')
        settings.published_at = datetime.now(timezone.utc)
    elif action == 'withdraw':
        settings.published_at = None
    elif action == 'save':
        notes = request.form.get('teacher_notes', '').strip()
        feedback = request.form.get('student_feedback', '').strip()
        reason = request.form.get('exclusion_reason', '').strip()
        include = request.form.get('include_in_progress') == 'on'
        if len(notes) > 8000 or len(feedback) > 8000 or len(reason) > 500 or (not include and not reason):
            abort(400, 'Notes/feedback must be within 8,000 characters. Excluding a session requires a reason within 500 characters.')
        settings.teacher_notes, settings.student_feedback = notes or None, feedback or None
        settings.include_in_progress, settings.exclusion_reason = include, reason or None
    else:
        abort(400)
    db.session.commit()
    flash('Report settings saved.', 'success')
    return redirect(url_for('learning.session_detail', session_id=session_id))


@learning_bp.get('/admin/analytics/sessions/<int:session_id>/export.zip')
@login_required
@admin_required
def export(session_id):
    report = build_session_report(_session(session_id), **_scope())
    return send_file(evidence_zip(report), mimetype='application/zip', as_attachment=True, download_name=f'learning-session-{session_id}.zip')


@learning_bp.get('/player/learning/sessions/<int:session_id>')
@login_required
def student_session(session_id):
    report = build_session_report(_session(session_id, student=True), player_id=current_user.id)
    return render_template('player/learning_session.html', report=report, student_view=True)


@learning_bp.get('/admin/analytics/sessions/<int:session_id>/student-preview/<int:player_id>')
@login_required
@admin_required
def student_preview(session_id, player_id):
    report = build_session_report(_session(session_id), player_id=player_id)
    if not report['students']:
        abort(404)
    return render_template('player/learning_session.html', report=report, student_view=True, preview=True)


def _result(session_id, question_id, player_id, *, student=False):
    session = _session(session_id, student=student)
    report = build_session_report(session, player_id=player_id)
    if not report['students']:
        abort(404)
    index = next((i for i, q in enumerate(report['questions']) if q['id'] == question_id), None)
    if index is None:
        abort(404)
    question = deepcopy(report['questions'][index])
    content = question['content'] or {}
    for block in content.get('body', {}).get('blocks', []):
        if block['type'] == 'image':
            block['image_url'] = url_for('learning.asset', session_id=session_id, name=block['asset_name']) if block.get('asset_name') else ''
    return render_template('player/learning_result.html' if student else 'admin/analytics/session_result.html',
                           report=report, question=question, learner=report['students'][0],
                           cell=report['students'][0]['cells'][index], student_view=student)


@learning_bp.get('/admin/analytics/sessions/<int:session_id>/results/<int:question_id>/<int:player_id>')
@login_required
@admin_required
def result_detail(session_id, question_id, player_id):
    return _result(session_id, question_id, player_id)


@learning_bp.get('/player/learning/sessions/<int:session_id>/questions/<int:question_id>')
@login_required
def student_result(session_id, question_id):
    return _result(session_id, question_id, current_user.id, student=True)


@learning_bp.get('/learning/sessions/<int:session_id>/assets/<name>')
@login_required
def asset(session_id, name):
    _session(session_id, student=not current_user.is_admin)
    if not ASSET_NAME.fullmatch(name):
        abort(404)
    query = AnalyticsRoundProblem.query.join(AnalyticsRound).filter(AnalyticsRound.session_id == session_id)
    if not any(name in snapshot_assets(q.content_snapshot_json) for q in query.all()):
        abort(404)
    path = asset_directory() / name
    if not path.is_file() or sha256(path.read_bytes()).hexdigest() != name.split('.')[0]:
        abort(404)
    response = send_file(path, conditional=True)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
