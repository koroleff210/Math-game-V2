"""Loopback-only identity adapter. Runs separately; no exam app restart/schema changes.

Uses the exam application's own User/StudentEnrollment models and SQLite settings.
Never returns password hashes. Bearer authentication is required for every request.
"""
import os
import re
import secrets

from flask import Flask, abort, jsonify, request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from exam_platform.models import db, User, StudentEnrollment

_dummy = generate_password_hash(secrets.token_urlsafe(32))


def create_gateway(config=None):
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL'),
                      SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      IDENTITY_TOKEN=os.environ.get('GAME_IDENTITY_TOKEN'),
                      IDENTITY_TEACHER_ID=os.environ.get('GAME_IDENTITY_TEACHER_ID'),
                      MAX_CONTENT_LENGTH=8192)
    if config:
        app.config.update(config)
    if len(app.config.get('IDENTITY_TOKEN') or '') < 32:
        raise RuntimeError('Identity gateway requires a strong private token.')
    db.init_app(app)

    @app.post('/identity')
    def identity():
        if request.remote_addr not in ('127.0.0.1', '::1'):
            abort(403)
        if not secrets.compare_digest(request.headers.get('Authorization', ''),
                                      'Bearer ' + app.config['IDENTITY_TOKEN']):
            abort(403)
        data = request.get_json(silent=True) or {}
        email = str(data.get('email', '')).strip().lower()
        action = data.get('action')
        if not 3 <= len(email) <= 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            abort(400)
        # Serialise password setup/reset with the existing exam application's writes.
        if action in ('provision', 'setup', 'reset') and db.engine.dialect.name == 'sqlite':
            db.session.execute(text('BEGIN IMMEDIATE'))
        user = db.session.scalar(db.select(User).where(User.email == email).with_for_update())
        if user and user.role != 'student':
            abort(409)
        if action == 'provision':
            if user is None:
                user = User(email=email, name=str(data.get('name') or email).strip()[:120], role='student')
                db.session.add(user)
                db.session.flush()
            teacher_id = app.config.get('IDENTITY_TEACHER_ID')
            if teacher_id:
                teacher = db.session.get(User, int(teacher_id))
            else:
                teachers = db.session.scalars(db.select(User).where(User.role == 'teacher')).all()
                if len(teachers) != 1:
                    abort(409)
                teacher = teachers[0]
            if not teacher or teacher.role != 'teacher':
                abort(409)
            enrollment = db.session.scalar(db.select(StudentEnrollment).where(
                StudentEnrollment.student_id == user.id, StudentEnrollment.teacher_id == teacher.id))
            if enrollment is None:
                db.session.add(StudentEnrollment(teacher_id=teacher.id, student_id=user.id))
            else:
                enrollment.active = True
        elif user is None:
            check_password_hash(_dummy, str(data.get('password', '')))
            abort(404)
        elif action == 'authenticate':
            password = str(data.get('password', ''))
            if not user.password_hash or not check_password_hash(user.password_hash, password):
                abort(401)
        elif action == 'setup':
            password = str(data.get('password', ''))
            if user.password_hash or not 8 <= len(password) <= 256:
                abort(409)
            user.password_hash = generate_password_hash(password)
            user.auth_version += 1
        elif action == 'reset':
            user.password_hash = None
            user.auth_version += 1
        elif action != 'lookup':
            abort(400)
        result = dict(id=user.id, email=user.email, name=user.name,
                      password_set=bool(user.password_hash), version=user.auth_version)
        db.session.commit()
        return jsonify(result)

    @app.after_request
    def secure(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(IntegrityError)
    def conflict(_):
        db.session.rollback()
        return jsonify(error='Concurrent identity change. Try again.'), 409

    return app
