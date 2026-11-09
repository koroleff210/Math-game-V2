"""Map authored assets to cacheable display derivatives without changing source paths."""
import json
from pathlib import Path
import re

from flask import render_template, request, url_for
from flask_login import current_user


def is_player_screen():
    return (
        request.blueprint in ('player', 'classic_player', 'boss_rush_player')
        and request.endpoint != 'player.gear_shell'
    ) or request.endpoint in ('learning.student_session', 'learning.student_result')


def register_ui_images(app):
    path = Path(app.static_folder)/'optimized'/'manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

    @app.before_request
    def player_screen_container():
        # A fullscreen document must survive navigation. Only real top-level
        # browser GETs receive the container; frame navigations, AJAX, POSTs and
        # downloads continue through the existing routes and access checks.
        if (request.method == 'GET' and is_player_screen()
                and request.headers.get('Sec-Fetch-Dest') == 'document'
                and current_user.is_authenticated):
            return render_template('player/screen.html', frame_url=request.full_path.rstrip('?'))

    @app.template_filter('ui_image')
    def ui_image(url):
        prefix = app.static_url_path + '/'
        if not isinstance(url, str) or not url.startswith(prefix):
            return url
        entry = manifest.get(url[len(prefix):])
        return prefix + entry['path'] if entry else url

    @app.template_filter('ui_image_tree')
    def ui_image_tree(value):
        if isinstance(value, dict):
            return {k: ui_image_tree(v) for k, v in value.items()}
        if isinstance(value, list):
            return [ui_image_tree(v) for v in value]
        return ui_image(value)

    @app.context_processor
    def ui_context():
        enabled = is_player_screen()
        background = None
        if request.endpoint in ('player.dashboard', 'player.progress', 'player.blacksmith'):
            name = 'blacksmith_bg.png' if request.endpoint == 'player.blacksmith' else 'background_001.png'
            background = ui_image(url_for('static', filename='classic_ui/player_ui/'+name))
        return {'ui_enhanced': enabled, 'ui_background': background}

    @app.after_request
    def cache_display_images(response):
        if is_player_screen():
            response.vary.add('Sec-Fetch-Dest')
            response.headers['Cache-Control'] = 'private, no-store'
        filename = (request.view_args or {}).get('filename', '')
        if request.endpoint == 'static' and re.fullmatch(r'optimized/[a-f0-9]{64}\.webp', filename):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response
