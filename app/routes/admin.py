# app/routes/admin.py
#
# Admin blueprint — all admin routes live here.
# Each route is protected by @login_required + @admin_required.
#
# Routes implemented in Phase 2:
#   /admin/                          — dashboard
#   /admin/topics                    — list + create topics
#   /admin/topics/<id>/delete        — POST: delete topic (blocked if has problems)
#   /admin/problems                  — list problems
#   /admin/problems/new              — create problem
#   /admin/problems/<id>/edit        — edit problem
#   /admin/problems/<id>/delete      — POST: delete problem
#   /admin/sets                      — list + create problem sets
#   /admin/sets/<id>                 — set detail + add/remove problems
#   /admin/sets/<id>/add             — POST: add problem to set
#   /admin/sets/<id>/remove/<pid>    — POST: remove problem from set
#   /admin/sets/<id>/delete          — POST: delete set (blocked if used by a session)
#
# Routes added in G2a:
#   /admin/subjects/                 — list subjects
#   /admin/subjects/new              — create subject
#   /admin/subjects/<id>/edit        — edit subject
#   /admin/subjects/<id>/delete      — POST: delete subject (blocked if has topics)

from datetime import datetime, timezone
import re
from urllib.parse import urlencode

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, abort, make_response
from flask_login import login_required
from sqlalchemy import select

from app.extensions import db
from app.decorators import admin_required
from app.models.player import Player
from app.models.subjects import Subject
from app.models.problems import (
    Topic,
    Problem,
    ProblemSet,
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    PROBLEM_ANSWER_TYPE_TEXT_INPUT,
    PROBLEM_CONTENT_KIND_DEFINITION,
    PROBLEM_CONTENT_KIND_PROBLEM,
)
from app.models.game import GameSession
from app.models.groups import PlayerGroup
from app.models.gear import GearItemDefinition
from app.models.history import RoundHistory, RoundPlayerResult, build_history_csv
from app.models.analytics import (
    AnalyticsAnswerAttempt,
    AnalyticsBossRushBattleEvent,
    AnalyticsClassicEconomyEvent,
    AnalyticsPlayerProblem,
    AnalyticsPlayerRound,
    AnalyticsRound,
    AnalyticsRoundProblem,
)
from app.routes.forms import TopicForm, SubjectForm, ProblemForm, ProblemSetForm, PlayerCreateForm, PlayerEditForm, PlayerGroupForm, DiamondAwardForm, GearItemForm
from app.services.progression import get_or_create_player_progression, award_diamonds_to_player
from app.services.analytics_reports import (
    build_class_dashboard,
    parse_date_filter,
    recent_groups_with_analytics,
)
from app.services.analytics_exports import (
    analytics_class_dashboard_filename,
    analytics_round_filename,
    build_class_dashboard_csv,
    build_round_detail_csv,
)
from app.services.gear import (
    list_admin_gear_catalog,
    build_admin_gear_item_view,
    create_admin_gear_item,
    delete_admin_gear_item,
    update_admin_gear_item,
    build_gear_image_select_choices,
    build_gear_image_select_choices_by_slot,
)
from app.services.problem_content import (
    ANSWER_TYPE_CHOICES,
    EDITOR_BLOCK_TYPE_CHOICES,
    GRAPH_COLOR_PALETTE,
    add_problem_block,
    add_problem_choice_option,
    add_graph_block_element,
    build_problem_body_view,
    build_problem_choice_view,
    build_graph_block_editor_view,
    delete_problem_block,
    delete_problem_choice_option,
    delete_graph_block_element,
    ensure_problem_default_accepted_answer,
    ensure_problem_default_block,
    ensure_problem_default_choice_options,
    has_saved_problem_accepted_answers,
    has_saved_problem_blocks,
    has_saved_problem_choice_options,
    move_problem_block,
    move_problem_choice_option,
    normalize_problem_block_positions,
    normalize_problem_choice_option_positions,
    replace_problem_accepted_answers,
    sync_problem_legacy_compat_fields,
    update_problem_block_content,
    update_problem_choice_options,
    uses_structured_problem_answers,
)
from app.models.progression import PlayerProgression, DiamondTransaction


admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

CONTENT_KIND_CHOICES = [
    (PROBLEM_CONTENT_KIND_PROBLEM, 'Problem'),
    (PROBLEM_CONTENT_KIND_DEFINITION, 'Definition'),
]

BUILDER_CONTENT_KIND_CHOICES = [
    ('all', 'All'),
    (PROBLEM_CONTENT_KIND_PROBLEM, 'Problems'),
    (PROBLEM_CONTENT_KIND_DEFINITION, 'Definitions'),
]

# Shorthand: both decorators are always used together on every admin route.
# Applied bottom-up: login_required runs first, then admin_required.


# ── Dashboard ─────────────────────────────────────────────────────────────────

@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    # Near-launch: keep /admin/ as a lightweight entry point and hand off to the
    # existing Classic launch flow rather than maintain a second dashboard
    # surface with overlapping navigation.
    return redirect(url_for('classic_admin.index'))


@admin_bp.route('/gear/')
@login_required
@admin_required
def gear_index():
    gear_items = list_admin_gear_catalog()
    return render_template('admin/gear/index.html', gear_items=gear_items)


@admin_bp.route('/gear/new', methods=['GET', 'POST'])
@login_required
@admin_required
def gear_new():
    form = GearItemForm()
    selected_slot_type = form.slot_type.data or form.slot_type.choices[0][0]
    form.image_key.choices = build_gear_image_select_choices(selected_slot_type)
    if form.validate_on_submit():
        try:
            item = create_admin_gear_item({
                'item_id': form.item_id.data,
                'name': form.name.data,
                'slot_type': form.slot_type.data,
                'description': form.description.data,
                'image_key': form.image_key.data,
                'avatar_asset_key': form.avatar_asset_key.data,
                'diamond_cost': form.diamond_cost.data,
                'mine_gold_delta': form.mine_gold_delta.data,
                'steal_gold_delta': form.steal_gold_delta.data,
                'shield_duration_delta': form.shield_duration_delta.data,
                'is_active': form.is_active.data,
                'is_blacksmith_visible': form.is_blacksmith_visible.data,
            })
            db.session.commit()
            flash(f'Gear item "{item.name}" created.', 'success')
            return redirect(url_for('admin.gear_index'))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')

    return render_template(
        'admin/gear/form.html',
        form=form,
        title='New Gear Item',
        gear_item=None,
        gear_item_view=None,
        gear_image_choices_by_slot=build_gear_image_select_choices_by_slot(),
    )


@admin_bp.route('/gear/<string:item_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def gear_edit(item_id):
    gear_item = db.session.get(GearItemDefinition, item_id)
    if gear_item is None:
        flash('Gear item not found.', 'error')
        return redirect(url_for('admin.gear_index'))

    form = GearItemForm(obj=gear_item)
    if request.method == 'GET':
        form.item_id.data = gear_item.id
        form.avatar_asset_key.data = gear_item.avatar_asset_key or ''
    selected_slot_type = form.slot_type.data or gear_item.slot_type
    form.image_key.choices = build_gear_image_select_choices(selected_slot_type)
    if request.method == 'GET':
        form.image_key.data = gear_item.image_key or ''

    if form.validate_on_submit():
        try:
            item = update_admin_gear_item(item_id, {
                'name': form.name.data,
                'slot_type': form.slot_type.data,
                'description': form.description.data,
                'image_key': form.image_key.data,
                'avatar_asset_key': form.avatar_asset_key.data,
                'diamond_cost': form.diamond_cost.data,
                'mine_gold_delta': form.mine_gold_delta.data,
                'steal_gold_delta': form.steal_gold_delta.data,
                'shield_duration_delta': form.shield_duration_delta.data,
                'is_active': form.is_active.data,
                'is_blacksmith_visible': form.is_blacksmith_visible.data,
            })
            db.session.commit()
            flash(f'Gear item "{item.name}" updated.', 'success')
            return redirect(url_for('admin.gear_index'))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')

    return render_template(
        'admin/gear/form.html',
        form=form,
        title='Edit Gear Item',
        gear_item=gear_item,
        gear_item_view=build_admin_gear_item_view(gear_item),
        gear_image_choices_by_slot=build_gear_image_select_choices_by_slot(),
    )


@admin_bp.route('/gear/<string:item_id>/delete', methods=['POST'])
@login_required
@admin_required
def gear_delete(item_id):
    try:
        result = delete_admin_gear_item(item_id)
        db.session.commit()
        flash(
            f'Gear item "{result["item_name"]}" deleted. '
            f'Removed from {result["removed_ownerships"]} player inventory row(s) '
            f'and cleared {result["cleared_loadout_slots"]} equipped slot(s).',
            'success',
        )
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')

    return redirect(url_for('admin.gear_index'))


# ── Topics ────────────────────────────────────────────────────────────────────

def _subject_choices():
    """Return SelectField choices for Subject: [(0, '— None —'), (id, name), ...]."""
    choices = [(0, '— None —')]
    choices += [(s.id, s.name) for s in Subject.query.order_by(Subject.name).all()]
    return choices


@admin_bp.route('/topics', methods=['GET', 'POST'])
@login_required
@admin_required
def topics():
    form = TopicForm()
    form.subject_id.choices = _subject_choices()

    if form.validate_on_submit():
        # Check for duplicate name before inserting.
        existing = Topic.query.filter_by(name=form.name.data.strip()).first()
        if existing:
            flash(f'Topic "{form.name.data}" already exists.', 'error')
        else:
            sid = form.subject_id.data if form.subject_id.data else None
            if sid == 0:
                sid = None
            topic = Topic(
                name=form.name.data.strip(),
                subject=(form.subject.data or '').strip() or None,
                subject_id=sid,
                description=(form.description.data or '').strip() or None,
            )
            db.session.add(topic)
            db.session.commit()
            flash(f'Topic "{topic.name}" created.', 'success')
            return redirect(url_for('admin.topics'))

    all_topics = Topic.query.order_by(Topic.name).all()
    return render_template('admin/topics.html', form=form, topics=all_topics)


# ── Problems ──────────────────────────────────────────────────────────────────

@admin_bp.route('/problems')
@login_required
@admin_required
def problems():
    subject_id = request.args.get('subject_id', 0, type=int)
    subjects = Subject.query.order_by(Subject.name).all()

    if subject_id:
        all_problems = (
            Problem.query
            .join(Topic, Problem.topic_id == Topic.id)
            .filter(Topic.subject_id == subject_id)
            .order_by(Problem.id.desc())
            .all()
        )
    else:
        all_problems = Problem.query.order_by(Problem.id.desc()).all()

    return render_template(
        'admin/problems.html',
        problems=all_problems,
        subjects=subjects,
        selected_subject_id=subject_id,
    )


# ── AJAX: topics by subject ───────────────────────────────────────────────────

@admin_bp.route('/topics/by_subject/<int:subject_id>')
@login_required
@admin_required
def topics_by_subject(subject_id):
    """Return JSON list of Topics scoped to a Subject (or all if subject_id==0)."""
    if subject_id == 0:
        topics = Topic.query.order_by(Topic.name).all()
    else:
        topics = Topic.query.filter_by(subject_id=subject_id).order_by(Topic.name).all()
    return jsonify({'topics': [{'id': t.id, 'name': t.name, 'subject_id': t.subject_id} for t in topics]})


# ── Helper ────────────────────────────────────────────────────────────────────

def _subject_choices_for_problem():
    """Return (subjects list, choices list) for the problem form subject helper."""
    subjects = Subject.query.order_by(Subject.name).all()
    return subjects


def _problem_editor_topic_choices():
    return [(t.id, t.name) for t in Topic.query.order_by(Topic.name).all()]


def _build_problem_editor_create_context(*, subject_helper_value: int):
    subjects = _subject_choices_for_problem()
    topic_choices = _problem_editor_topic_choices()
    return {
        'problem': None,
        'create_mode': True,
        'subjects': subjects,
        'topic_choices': topic_choices,
        'subject_helper_value': subject_helper_value,
        'selected_topic_id': request.form.get('topic_id', type=int),
        'title_value': request.form.get('title', ''),
        'difficulty_value': request.form.get('difficulty', type=int) or 1,
        'answer_type_value': request.form.get('answer_type', 'text_input'),
        'content_kind_value': request.form.get('content_kind', PROBLEM_CONTENT_KIND_PROBLEM),
        'answer_type_choices': ANSWER_TYPE_CHOICES,
        'content_kind_choices': CONTENT_KIND_CHOICES,
        'block_type_choices': EDITOR_BLOCK_TYPE_CHOICES,
        'graph_color_palette': GRAPH_COLOR_PALETTE,
        'graph_color_palette_values': {row['value'] for row in GRAPH_COLOR_PALETTE},
    }


def _validate_topic_subject(subject_helper, topic):
    """
    Server-side subject/topic consistency check.
    Returns an error string if invalid, else None.
      - subject_helper == 0: any valid topic is allowed.
      - subject_helper != 0: topic.subject_id must equal subject_helper.
      - topic with NULL subject_id is invalid under a non-zero subject selection.
    """
    if subject_helper == 0:
        return None  # Any topic is fine.
    if topic.subject_id != subject_helper:
        return 'The selected topic does not belong to the chosen subject.'
    return None


@admin_bp.route('/problems/new', methods=['GET', 'POST'])
@login_required
@admin_required
def problem_new():
    if request.method == 'POST':
        subject_helper = request.form.get('subject_helper', 0, type=int)
        topic_id = request.form.get('topic_id', type=int)
        topic = db.session.get(Topic, topic_id)
        err = _validate_topic_subject(subject_helper, topic)
        title = (request.form.get('title') or '').strip()
        answer_type = (request.form.get('answer_type') or 'text_input').strip()
        content_kind = (request.form.get('content_kind') or PROBLEM_CONTENT_KIND_PROBLEM).strip()
        difficulty = request.form.get('difficulty', type=int) or 1
        if err:
            flash(err, 'error')
        elif not title:
            flash('Title is required.', 'error')
        elif not topic_id:
            flash('Topic is required.', 'error')
        elif answer_type not in {PROBLEM_ANSWER_TYPE_TEXT_INPUT, PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE}:
            flash('Unsupported answer type.', 'error')
        elif content_kind not in {PROBLEM_CONTENT_KIND_PROBLEM, PROBLEM_CONTENT_KIND_DEFINITION}:
            flash('Unsupported content kind.', 'error')
        else:
            problem = Problem(
                topic_id=topic_id,
                title=title,
                prompt_text='',
                answer_text='',
                answer_type=answer_type,
                content_kind=content_kind,
                difficulty=difficulty,
                image_path=None,
            )
            db.session.add(problem)
            db.session.flush()
            ensure_problem_default_block(problem)
            if answer_type == 'multiple_choice':
                ensure_problem_default_choice_options(problem, count=4)
            db.session.commit()
            flash(f'Problem "{problem.title}" created.', 'success')
            return redirect(url_for('admin.problem_content', problem_id=problem.id))

    subject_helper_value = request.form.get('subject_helper', 0, type=int)
    return render_template('admin/problem_content.html', **_build_problem_editor_create_context(subject_helper_value=subject_helper_value))


@admin_bp.route('/problems/<int:problem_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def problem_edit(problem_id):
    return problem_content(problem_id)


def _get_problem_or_redirect(problem_id):
    problem = db.session.get(Problem, problem_id)
    if problem is None:
        flash('Problem not found.', 'error')
        return None
    return problem


def _problem_content_redirect(problem_id, *, anchor: str | None = None):
    target = url_for('admin.problem_content', problem_id=problem_id)
    if anchor:
        target = f'{target}#{anchor}'
    return redirect(target)


def _build_problem_content_context(problem):
    normalize_problem_block_positions(problem)
    normalize_problem_choice_option_positions(problem)
    body_view = build_problem_body_view(problem)
    choice_view = build_problem_choice_view(problem)
    graph_editor_views = {
        block.id: build_graph_block_editor_view(block)
        for block in problem.blocks
        if block.block_type == 'graph'
    }
    accepted_answers_text = '\n'.join(row.answer_text for row in problem.accepted_answers)
    if not accepted_answers_text and (problem.answer_text or '').strip():
        accepted_answers_text = problem.answer_text.strip()
    has_structured_body = has_saved_problem_blocks(problem)
    has_structured_answers = has_saved_problem_accepted_answers(problem)
    has_choice_options = has_saved_problem_choice_options(problem)
    if problem.answer_type == 'multiple_choice':
        if has_choice_options:
            answer_source_label = 'saved multiple-choice options'
        else:
            answer_source_label = 'no saved multiple-choice options yet'
    else:
        if has_structured_answers:
            answer_source_label = 'accepted-answer rows'
        else:
            answer_source_label = 'legacy answer_text fallback'
    return {
        'problem': problem,
        'create_mode': False,
        'body_view': body_view,
        'choice_view': choice_view,
        'answer_type_choices': ANSWER_TYPE_CHOICES,
        'content_kind_choices': CONTENT_KIND_CHOICES,
        'block_type_choices': EDITOR_BLOCK_TYPE_CHOICES,
        'subjects': _subject_choices_for_problem(),
        'topic_choices': _problem_editor_topic_choices(),
        'subject_helper_value': problem.topic.subject_id or 0,
        'selected_topic_id': problem.topic_id,
        'title_value': problem.title,
        'difficulty_value': problem.difficulty,
        'answer_type_value': problem.answer_type,
        'content_kind_value': problem.content_kind,
        'accepted_answers_text': accepted_answers_text,
        'graph_editor_views': graph_editor_views,
        'graph_color_palette': GRAPH_COLOR_PALETTE,
        'graph_color_palette_values': {row['value'] for row in GRAPH_COLOR_PALETTE},
        'has_structured_body': has_structured_body,
        'has_structured_answers': has_structured_answers,
        'has_choice_options': has_choice_options,
        'answer_source_label': answer_source_label,
    }


@admin_bp.route('/problems/<int:problem_id>/content', methods=['GET', 'POST'])
@login_required
@admin_required
def problem_content(problem_id):
    problem = _get_problem_or_redirect(problem_id)
    if problem is None:
        return redirect(url_for('admin.problems'))

    if request.method == 'POST':
        try:
            if 'subject_helper' in request.form or 'topic_id' in request.form:
                subject_helper = request.form.get('subject_helper', 0, type=int)
                topic_id = request.form.get('topic_id', type=int)
                if not topic_id:
                    raise ValueError('Topic is required.')
                topic = db.session.get(Topic, topic_id)
                err = _validate_topic_subject(subject_helper, topic)
                if err:
                    raise ValueError(err)
                problem.topic_id = topic_id

            if 'title' in request.form:
                title = (request.form.get('title') or '').strip()
                if not title:
                    raise ValueError('Title is required.')
                problem.title = title

            if 'difficulty' in request.form:
                problem.difficulty = request.form.get('difficulty', type=int) or problem.difficulty

            selected_answer_type = (request.form.get('answer_type') or '').strip() or 'text_input'
            if selected_answer_type not in {'text_input', 'multiple_choice'}:
                raise ValueError('Unsupported answer type.')
            selected_content_kind = (request.form.get('content_kind') or '').strip() or PROBLEM_CONTENT_KIND_PROBLEM
            if selected_content_kind not in {PROBLEM_CONTENT_KIND_PROBLEM, PROBLEM_CONTENT_KIND_DEFINITION}:
                raise ValueError('Unsupported content kind.')

            if selected_answer_type == 'multiple_choice' and not problem.choice_options:
                ensure_problem_default_choice_options(problem, count=4)

            problem.answer_type = selected_answer_type
            problem.content_kind = selected_content_kind
            if selected_answer_type == 'text_input':
                answer_lines = (request.form.get('accepted_answers_text') or '').splitlines()
                replace_problem_accepted_answers(problem, answer_lines)
            else:
                if not problem.choice_options:
                    ensure_problem_default_choice_options(problem, count=4)
                    db.session.commit()
                    flash('Multiple-choice options initialized. Fill them in and save again.', 'success')
                    return _problem_content_redirect(problem.id, anchor='answer-mode')
                correct_option_id_raw = request.form.get('correct_option_id')
                try:
                    correct_option_id = int(correct_option_id_raw) if correct_option_id_raw else None
                except (TypeError, ValueError):
                    correct_option_id = None
                choice_payloads = []
                for option in sorted(problem.choice_options, key=lambda row: (row.position, row.id or 0)):
                    choice_payloads.append({
                        'option_id': option.id,
                        'option_text': request.form.get(f'choice_{option.id}_option_text'),
                    })
                update_problem_choice_options(problem, choice_payloads, correct_option_id)

            for block in sorted(problem.blocks, key=lambda row: (row.position, row.id or 0)):
                graph_editor = build_graph_block_editor_view(block) if block.block_type == 'graph' else None
                graph_equations = []
                graph_points = []
                if graph_editor:
                    for equation in graph_editor['equations']:
                        prefix = f'block_{block.id}_equation_{equation["id"]}'
                        graph_equations.append({
                            'id': equation['id'],
                            'label': request.form.get(f'{prefix}_label'),
                            'color': request.form.get(f'{prefix}_color'),
                            'equation_text': request.form.get(f'{prefix}_equation_text'),
                            'x_min': request.form.get(f'{prefix}_x_min'),
                            'x_max': request.form.get(f'{prefix}_x_max'),
                        })
                    for point in graph_editor['points']:
                        prefix = f'block_{block.id}_point_{point["id"]}'
                        graph_points.append({
                            'id': point['id'],
                            'label': request.form.get(f'{prefix}_label'),
                            'color': request.form.get(f'{prefix}_color'),
                            'coordinates_text': request.form.get(f'{prefix}_coordinates_text'),
                        })

                payload = {
                    'text_content': request.form.get(f'block_{block.id}_text_content'),
                    'image_path': request.form.get(f'block_{block.id}_image_path'),
                    'image_width_pct': request.form.get(f'block_{block.id}_image_width_pct'),
                    'graph_x_min': request.form.get(f'block_{block.id}_graph_x_min'),
                    'graph_x_max': request.form.get(f'block_{block.id}_graph_x_max'),
                    'graph_y_min': request.form.get(f'block_{block.id}_graph_y_min'),
                    'graph_y_max': request.form.get(f'block_{block.id}_graph_y_max'),
                    'graph_x_label': request.form.get(f'block_{block.id}_graph_x_label'),
                    'graph_y_label': request.form.get(f'block_{block.id}_graph_y_label'),
                    'graph_show_grid': request.form.get(f'block_{block.id}_graph_show_grid'),
                    'graph_equations': graph_equations,
                    'graph_points': graph_points,
                }
                update_problem_block_content(problem, block.id, payload)

            sync_problem_legacy_compat_fields(problem)
            db.session.commit()
            flash(f'Problem content for "{problem.title}" saved.', 'success')
            return redirect(url_for('admin.problem_content', problem_id=problem.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
            problem = db.session.get(Problem, problem_id)
            if problem is None:
                return redirect(url_for('admin.problems'))

    return render_template(
        'admin/problem_content.html',
        **_build_problem_content_context(problem),
    )


@admin_bp.route('/problems/<int:problem_id>/blocks/add', methods=['POST'])
@login_required
@admin_required
def problem_block_add(problem_id):
    problem = _get_problem_or_redirect(problem_id)
    if problem is None:
        return redirect(url_for('admin.problems'))

    block_type = (request.form.get('block_type') or request.args.get('block_type') or '').strip()
    after_block_id = request.form.get('after_block_id', type=int)
    if after_block_id is None:
        after_block_id = request.args.get('after_block_id', type=int)
    try:
        block = add_problem_block(problem, block_type, after_block_id=after_block_id)
        db.session.commit()
        flash('Problem block added.', 'success')
        return _problem_content_redirect(problem_id, anchor=f'block-{block.id}')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return _problem_content_redirect(problem_id, anchor='body-blocks')


@admin_bp.route('/problems/<int:problem_id>/blocks/initialize', methods=['POST'])
@login_required
@admin_required
def problem_block_initialize(problem_id):
    problem = _get_problem_or_redirect(problem_id)
    if problem is None:
        return redirect(url_for('admin.problems'))

    try:
        block = ensure_problem_default_block(problem)
        db.session.commit()
        flash('Structured body initialized from the legacy prompt.', 'success')
        return _problem_content_redirect(problem_id, anchor=f'block-{block.id}')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return _problem_content_redirect(problem_id, anchor='body-blocks')


@admin_bp.route('/problems/<int:problem_id>/choices/add', methods=['POST'])
@login_required
@admin_required
def problem_choice_option_add(problem_id):
    problem = _get_problem_or_redirect(problem_id)
    if problem is None:
        return redirect(url_for('admin.problems'))

    try:
        add_problem_choice_option(problem)
        db.session.commit()
        flash('Choice option added.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return _problem_content_redirect(problem_id, anchor='answer-mode')


@admin_bp.route('/problems/<int:problem_id>/blocks/<int:block_id>/move', methods=['POST'])
@login_required
@admin_required
def problem_block_move(problem_id, block_id):
    problem = _get_problem_or_redirect(problem_id)
    if problem is None:
        return redirect(url_for('admin.problems'))

    direction = (request.form.get('direction') or '').strip().lower()
    try:
        move_problem_block(problem, block_id, direction)
        db.session.commit()
        return _problem_content_redirect(problem_id, anchor=f'block-{block_id}')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return _problem_content_redirect(problem_id, anchor='body-blocks')


@admin_bp.route('/problems/<int:problem_id>/blocks/<int:block_id>/delete', methods=['POST'])
@login_required
@admin_required
def problem_block_delete(problem_id, block_id):
    problem = _get_problem_or_redirect(problem_id)
    if problem is None:
        return redirect(url_for('admin.problems'))

    try:
        delete_problem_block(problem, block_id)
        db.session.commit()
        flash('Problem block deleted.', 'success')
        return _problem_content_redirect(problem_id, anchor='body-blocks')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return _problem_content_redirect(problem_id, anchor='body-blocks')


@admin_bp.route('/problems/<int:problem_id>/blocks/<int:block_id>/graph-elements/add', methods=['POST'])
@login_required
@admin_required
def problem_graph_element_add(problem_id, block_id):
    problem = _get_problem_or_redirect(problem_id)
    if problem is None:
        return redirect(url_for('admin.problems'))

    block = next((row for row in problem.blocks if row.id == block_id), None)
    if block is None:
        flash('Problem block not found.', 'error')
        return redirect(url_for('admin.problem_content', problem_id=problem_id))

    element_type = (request.form.get('graph_element_type') or request.args.get('graph_element_type') or '').strip()
    try:
        add_graph_block_element(block, element_type)
        db.session.commit()
        flash('Graph element added.', 'success')
        return _problem_content_redirect(problem_id, anchor=f'block-{block_id}')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return _problem_content_redirect(problem_id, anchor=f'block-{block_id}')


@admin_bp.route('/problems/<int:problem_id>/blocks/<int:block_id>/graph-elements/<string:element_id>/delete', methods=['POST'])
@login_required
@admin_required
def problem_graph_element_delete(problem_id, block_id, element_id):
    problem = _get_problem_or_redirect(problem_id)
    if problem is None:
        return redirect(url_for('admin.problems'))

    block = next((row for row in problem.blocks if row.id == block_id), None)
    if block is None:
        flash('Problem block not found.', 'error')
        return redirect(url_for('admin.problem_content', problem_id=problem_id))

    try:
        delete_graph_block_element(block, element_id)
        db.session.commit()
        flash('Graph element deleted.', 'success')
        return _problem_content_redirect(problem_id, anchor=f'block-{block_id}')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return _problem_content_redirect(problem_id, anchor=f'block-{block_id}')


@admin_bp.route('/problems/<int:problem_id>/choices/<int:option_id>/move', methods=['POST'])
@login_required
@admin_required
def problem_choice_option_move(problem_id, option_id):
    problem = _get_problem_or_redirect(problem_id)
    if problem is None:
        return redirect(url_for('admin.problems'))

    direction = (request.form.get('direction') or '').strip().lower()
    try:
        move_problem_choice_option(problem, option_id, direction)
        db.session.commit()
        return _problem_content_redirect(problem_id, anchor='answer-mode')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return _problem_content_redirect(problem_id, anchor='answer-mode')


@admin_bp.route('/problems/<int:problem_id>/choices/<int:option_id>/delete', methods=['POST'])
@login_required
@admin_required
def problem_choice_option_delete(problem_id, option_id):
    problem = _get_problem_or_redirect(problem_id)
    if problem is None:
        return redirect(url_for('admin.problems'))

    try:
        delete_problem_choice_option(problem, option_id)
        db.session.commit()
        flash('Choice option deleted.', 'success')
        return _problem_content_redirect(problem_id, anchor='answer-mode')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return _problem_content_redirect(problem_id, anchor='answer-mode')


# ── Problem Sets ──────────────────────────────────────────────────────────────

def _parse_problem_set_builder_filters(source):
    subject_id = source.get('subject_id', type=int) or 0
    difficulty = source.get('difficulty', type=int) or 0
    raw_answer_type = (source.get('answer_type') or PROBLEM_ANSWER_TYPE_TEXT_INPUT).strip()
    if raw_answer_type not in {
        PROBLEM_ANSWER_TYPE_TEXT_INPUT,
        PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    }:
        raw_answer_type = PROBLEM_ANSWER_TYPE_TEXT_INPUT
    raw_content_kind = (source.get('content_kind') or 'all').strip()
    if raw_content_kind not in {'all', PROBLEM_CONTENT_KIND_PROBLEM, PROBLEM_CONTENT_KIND_DEFINITION}:
        raw_content_kind = 'all'
    preview_problem_id = source.get('preview_problem_id', type=int)
    topic_ids = [
        topic_id
        for topic_id in source.getlist('topic_id', type=int)
        if topic_id
    ]
    unique_topic_ids = list(dict.fromkeys(topic_ids))
    return {
        'subject_id': subject_id,
        'topic_ids': unique_topic_ids,
        'difficulty': difficulty,
        'answer_type': raw_answer_type,
        'content_kind': raw_content_kind,
        'preview_problem_id': preview_problem_id,
    }


def _problem_set_builder_query_items(filter_state, *, preview_problem_id=None):
    preview_id = filter_state.get('preview_problem_id') if preview_problem_id is None else preview_problem_id
    items = []
    subject_id = filter_state.get('subject_id') or 0
    difficulty = filter_state.get('difficulty') or 0
    answer_type = filter_state.get('answer_type') or PROBLEM_ANSWER_TYPE_TEXT_INPUT
    content_kind = filter_state.get('content_kind') or 'all'
    if subject_id:
        items.append(('subject_id', subject_id))
    for topic_id in filter_state.get('topic_ids', []):
        items.append(('topic_id', topic_id))
    if difficulty:
        items.append(('difficulty', difficulty))
    if answer_type:
        items.append(('answer_type', answer_type))
    if content_kind and content_kind != 'all':
        items.append(('content_kind', content_kind))
    if preview_id:
        items.append(('preview_problem_id', preview_id))
    return items


def _problem_set_builder_redirect(set_id, filter_state, *, preview_problem_id=None):
    target = url_for('admin.problem_set_detail', set_id=set_id)
    query_items = _problem_set_builder_query_items(filter_state, preview_problem_id=preview_problem_id)
    if query_items:
        target = f'{target}?{urlencode(query_items, doseq=True)}'
    target = f'{target}#builder-workspace'
    return redirect(target)


def _problem_set_builder_preview_url(set_id, filter_state, problem_id):
    target = url_for('admin.problem_set_detail', set_id=set_id)
    query_items = _problem_set_builder_query_items(filter_state, preview_problem_id=problem_id)
    if query_items:
        target = f'{target}?{urlencode(query_items, doseq=True)}'
    target = f'{target}#builder-workspace'
    return target


def _problem_builder_source_label(problem):
    metadata = getattr(problem, 'source_metadata', None)
    if metadata:
        return metadata.source_id or metadata.canonical_id or f'#{problem.id}'
    return f'#{problem.id}'


def _problem_builder_metadata_value(problem, key):
    metadata = getattr(problem, 'source_metadata', None)
    raw = getattr(metadata, 'raw_metadata_json', None) if metadata else None
    if isinstance(raw, dict):
        value = raw.get(key)
        if value not in (None, ''):
            if isinstance(value, list):
                return ', '.join(str(item) for item in value if item not in (None, ''))
            return str(value)
    return ''


def _problem_builder_prompt_excerpt(body_view, *, length=110):
    parts = []
    for block in (body_view or {}).get('blocks', []):
        if block.get('type') == 'rich_text':
            text = re.sub(r'<[^>]+>', ' ', block.get('rendered_html') or block.get('text_content') or '')
            text = re.sub(r'\s+', ' ', text).strip()
            if text:
                parts.append(text)
    excerpt = ' '.join(parts).strip()
    if len(excerpt) > length:
        return excerpt[:length].rstrip() + '...'
    return excerpt


def _problem_builder_option_status(problem):
    if problem.answer_type != PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE:
        return 'text input'
    options = [option.option_text for option in sorted(problem.choice_options, key=lambda row: (row.position, row.id or 0))]
    if [text.strip() for text in options] == ['A', 'B', 'C', 'D']:
        return 'artificial A/B/C/D'
    return 'explicit options' if options else 'no options'


def _problem_builder_row(problem, filter_state, set_id):
    body_view = build_problem_body_view(problem)
    image_count = sum(1 for block in body_view['blocks'] if block['type'] == 'image')
    return {
        'problem': problem,
        'preview_url': _problem_set_builder_preview_url(set_id, filter_state, problem.id),
        'source_label': _problem_builder_source_label(problem),
        'topic_label': problem.topic.name if problem.topic else '',
        'subject_label': (problem.topic.subject_obj.name if problem.topic and getattr(problem.topic, 'subject_obj', None) else (problem.topic.subject if problem.topic else '')),
        'level_label': _problem_builder_metadata_value(problem, 'level'),
        'prompt_excerpt': _problem_builder_prompt_excerpt(body_view),
        'image_count': image_count,
        'option_status': _problem_builder_option_status(problem),
        'content_kind_label': 'Definition' if problem.content_kind == PROBLEM_CONTENT_KIND_DEFINITION else 'Problem',
    }


def _build_problem_set_preview_context(preview_problem):
    preview_body_view = build_problem_body_view(preview_problem) if preview_problem else None
    preview_choice_view = build_problem_choice_view(preview_problem) if preview_problem else None
    preview_metadata = None
    if preview_problem:
        preview_body_blocks = (preview_body_view or {}).get('blocks', [])
        metadata = getattr(preview_problem, 'source_metadata', None)
        preview_metadata = {
            'source_system': metadata.source_system if metadata else '',
            'source_id': metadata.source_id if metadata else '',
            'canonical_id': metadata.canonical_id if metadata else '',
            'subject': (preview_problem.topic.subject_obj.name if preview_problem.topic and getattr(preview_problem.topic, 'subject_obj', None) else (preview_problem.topic.subject if preview_problem.topic else '')),
            'topic': preview_problem.topic.name if preview_problem.topic else '',
            'subtopic': _problem_builder_metadata_value(preview_problem, 'subtopics'),
            'difficulty': preview_problem.difficulty,
            'level': _problem_builder_metadata_value(preview_problem, 'level'),
            'answer_type': 'Multiple choice' if preview_problem.answer_type == PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE else 'Text input',
            'content_kind': 'Definition' if preview_problem.content_kind == PROBLEM_CONTENT_KIND_DEFINITION else 'Problem',
            'image_count': sum(1 for block in preview_body_blocks if block.get('type') == 'image'),
            'option_status': _problem_builder_option_status(preview_problem),
        }
    return {
        'preview_problem': preview_problem,
        'preview_body_view': preview_body_view,
        'preview_choice_view': preview_choice_view,
        'preview_metadata': preview_metadata,
    }


def _build_problem_set_detail_context(pset, filter_state):
    settings_form = ProblemSetForm(obj=pset)
    set_problems = pset.problems.order_by(Problem.id).all()
    set_problem_ids = {problem.id for problem in set_problems}
    subjects = Subject.query.order_by(Subject.name).all()

    topics_for_subject = []
    valid_topic_ids = []
    if filter_state['subject_id']:
        topics_for_subject = (
            Topic.query
            .filter_by(subject_id=filter_state['subject_id'])
            .order_by(Topic.name)
            .all()
        )
        allowed_topic_ids = {topic.id for topic in topics_for_subject}
        valid_topic_ids = [
            topic_id for topic_id in filter_state['topic_ids']
            if topic_id in allowed_topic_ids
        ]

    query = Problem.query.filter(Problem.answer_type == filter_state['answer_type'])
    if filter_state['content_kind'] != 'all':
        query = query.filter(Problem.content_kind == filter_state['content_kind'])
    if filter_state['subject_id']:
        query = query.join(Topic, Problem.topic_id == Topic.id).filter(Topic.subject_id == filter_state['subject_id'])
        if valid_topic_ids:
            query = query.filter(Problem.topic_id.in_(valid_topic_ids))
    if set_problem_ids:
        query = query.filter(~Problem.id.in_(set_problem_ids))
    if filter_state['difficulty']:
        query = query.filter(Problem.difficulty == filter_state['difficulty'])
    available_problems = query.order_by(Problem.id).all()

    preview_problem = None
    requested_preview_id = filter_state.get('preview_problem_id')
    if requested_preview_id:
        for candidate in available_problems + set_problems:
            if candidate.id == requested_preview_id:
                preview_problem = candidate
                break
    if preview_problem is None and available_problems:
        preview_problem = available_problems[0]
    if preview_problem is None and set_problems:
        preview_problem = set_problems[0]

    available_problem_rows = [_problem_builder_row(problem, filter_state, pset.id) for problem in available_problems]
    set_problem_rows = [_problem_builder_row(problem, filter_state, pset.id) for problem in set_problems]

    return {
        'pset': pset,
        'subjects': subjects,
        'topics_for_subject': topics_for_subject,
        'selected_subject_id': filter_state['subject_id'],
        'selected_topic_ids': valid_topic_ids,
        'selected_difficulty': filter_state['difficulty'],
        'selected_answer_type': filter_state['answer_type'],
        'selected_content_kind': filter_state['content_kind'],
        'content_kind_choices': BUILDER_CONTENT_KIND_CHOICES,
        'filter_state': {
            **filter_state,
            'topic_ids': valid_topic_ids,
        },
        'available_problem_rows': available_problem_rows,
        'set_problem_rows': set_problem_rows,
        **_build_problem_set_preview_context(preview_problem),
        'settings_form': settings_form,
    }


@admin_bp.route('/sets', methods=['GET', 'POST'])
@login_required
@admin_required
def problem_sets():
    form = ProblemSetForm()

    if form.validate_on_submit():
        pset = ProblemSet(
            name=form.name.data.strip(),
            description=(form.description.data or '').strip() or None,
            usable_in_classic=form.usable_in_classic.data,
            usable_in_boss_rush=form.usable_in_boss_rush.data,
            usable_as_recovery=form.usable_as_recovery.data,
            usable_in_team=form.usable_in_team.data,
        )
        db.session.add(pset)
        db.session.commit()
        flash(f'Problem set "{pset.name}" created.', 'success')
        return redirect(url_for('admin.problem_sets'))

    all_sets = ProblemSet.query.order_by(ProblemSet.id.desc()).all()
    return render_template('admin/problem_sets.html', form=form, sets=all_sets)


@admin_bp.route('/sets/<int:set_id>')
@login_required
@admin_required
def problem_set_detail(set_id):
    pset = db.session.get(ProblemSet, set_id)
    if pset is None:
        flash('Problem set not found.', 'error')
        return redirect(url_for('admin.problem_sets'))

    filter_state = _parse_problem_set_builder_filters(request.args)
    return render_template('admin/problem_set_detail.html', **_build_problem_set_detail_context(pset, filter_state))


@admin_bp.route('/sets/<int:set_id>/preview/<int:problem_id>')
@login_required
@admin_required
def problem_set_preview(set_id, problem_id):
    pset = db.session.get(ProblemSet, set_id)
    if pset is None:
        abort(404)
    problem = db.session.get(Problem, problem_id)
    if problem is None:
        abort(404)
    html = render_template(
        'admin/_problem_set_builder_preview.html',
        **_build_problem_set_preview_context(problem),
    )
    return jsonify({
        'html': html,
        'problem_id': problem.id,
        'title': problem.title,
    })


@admin_bp.route('/sets/<int:set_id>/settings', methods=['POST'])
@login_required
@admin_required
def problem_set_settings(set_id):
    pset = db.session.get(ProblemSet, set_id)
    if pset is None:
        flash('Problem set not found.', 'error')
        return redirect(url_for('admin.problem_sets'))

    form = ProblemSetForm()
    if form.validate_on_submit():
        pset.name = form.name.data.strip()
        pset.description = (form.description.data or '').strip() or None
        pset.usable_in_classic = form.usable_in_classic.data
        pset.usable_in_boss_rush = form.usable_in_boss_rush.data
        pset.usable_as_recovery = form.usable_as_recovery.data
        pset.usable_in_team = form.usable_in_team.data
        db.session.commit()
        flash(f'Problem set "{pset.name}" settings updated.', 'success')
    else:
        flash('Problem set settings could not be saved. Check the highlighted fields.', 'error')
    return redirect(url_for('admin.problem_set_detail', set_id=set_id))


@admin_bp.route('/sets/<int:set_id>/add', methods=['POST'])
@login_required
@admin_required
def problem_set_add(set_id):
    pset = db.session.get(ProblemSet, set_id)
    if pset is None:
        flash('Problem set not found.', 'error')
        return redirect(url_for('admin.problem_sets'))

    filter_state = _parse_problem_set_builder_filters(request.form)
    problem_id = request.form.get('problem_id', type=int)
    problem = db.session.get(Problem, problem_id) if problem_id else None

    if problem is None:
        flash('Problem not found.', 'error')
    elif problem in pset.problems.all():
        flash('Problem is already in this set.', 'error')
    else:
        pset.problems.append(problem)
        db.session.commit()
        flash(f'Problem "{problem.title}" added to set.', 'success')

    return _problem_set_builder_redirect(set_id, filter_state, preview_problem_id=problem_id)


@admin_bp.route('/sets/<int:set_id>/remove/<int:problem_id>', methods=['POST'])
@login_required
@admin_required
def problem_set_remove(set_id, problem_id):
    pset = db.session.get(ProblemSet, set_id)
    if pset is None:
        flash('Problem set not found.', 'error')
        return redirect(url_for('admin.problem_sets'))

    filter_state = _parse_problem_set_builder_filters(request.form)
    problem = db.session.get(Problem, problem_id)
    if problem and problem in pset.problems.all():
        pset.problems.remove(problem)
        db.session.commit()
        flash(f'Problem "{problem.title}" removed from set.', 'success')
    else:
        flash('Problem not found in this set.', 'error')

    return _problem_set_builder_redirect(set_id, filter_state)


# ── Delete operations ─────────────────────────────────────────────────────────

@admin_bp.route('/topics/<int:topic_id>/delete', methods=['POST'])
@login_required
@admin_required
def topic_delete(topic_id):
    topic = db.session.get(Topic, topic_id)
    if topic is None:
        flash('Topic not found.', 'error')
        return redirect(url_for('admin.topics'))

    if topic.problems.count() > 0:
        flash(
            f'Cannot delete topic "{topic.name}" — it still contains '
            f'{topic.problems.count()} problem(s). Remove or reassign them first.',
            'error',
        )
        return redirect(url_for('admin.topics'))

    db.session.delete(topic)
    db.session.commit()
    flash(f'Topic "{topic.name}" deleted.', 'success')
    return redirect(url_for('admin.topics'))


@admin_bp.route('/problems/<int:problem_id>/delete', methods=['POST'])
@login_required
@admin_required
def problem_delete(problem_id):
    problem = db.session.get(Problem, problem_id)
    if problem is None:
        flash('Problem not found.', 'error')
        return redirect(url_for('admin.problems'))

    # Many-to-many association rows are removed automatically by SQLAlchemy
    # when the Problem is deleted (cascade through the secondary table).
    title = problem.title
    db.session.delete(problem)
    db.session.commit()
    flash(f'Problem "{title}" deleted.', 'success')
    return redirect(url_for('admin.problems'))


@admin_bp.route('/sets/<int:set_id>/delete', methods=['POST'])
@login_required
@admin_required
def problem_set_delete(set_id):
    pset = db.session.get(ProblemSet, set_id)
    if pset is None:
        flash('Problem set not found.', 'error')
        return redirect(url_for('admin.problem_sets'))

    # Block deletion if any session references this set.
    in_use = GameSession.query.filter_by(problem_set_id=set_id).first()
    if in_use:
        flash(
            f'Cannot delete set "{pset.name}" — it is used by session #{in_use.id}. '
            'Archive or reassign that session first.',
            'error',
        )
        return redirect(url_for('admin.problem_sets'))

    name = pset.name
    db.session.delete(pset)
    db.session.commit()
    flash(f'Problem set "{name}" deleted.', 'success')
    return redirect(url_for('admin.problem_sets'))


# ── Players ─────────────────────────────────────────────────────

@admin_bp.route('/players/')
@login_required
@admin_required
def players_index():
    all_players = Player.query.order_by(Player.username).all()
    form = PlayerCreateForm()
    return render_template('admin/players/index.html', players=all_players, form=form, create_open=False)


@admin_bp.route('/players/new', methods=['GET', 'POST'])
@login_required
@admin_required
def player_new():
    form = PlayerCreateForm()
    if request.method == 'GET':
        all_players = Player.query.order_by(Player.username).all()
        return render_template('admin/players/index.html', players=all_players, form=form, create_open=True)
    if form.validate_on_submit():
        existing = db.session.execute(
            select(Player).where(Player.username == form.username.data.strip())
        ).scalar_one_or_none()
        if existing:
            flash(f'Username "{form.username.data}" is already taken.', 'error')
        else:
            player = Player(
                username=form.username.data.strip(),
                is_admin=form.is_admin.data,
                yeargroup=(form.yeargroup.data or '').strip() or None,
            )
            player.set_password(form.password.data)
            db.session.add(player)
            db.session.commit()
            flash(f'Player "{player.username}" created.', 'success')
            return redirect(url_for('admin.players_index'))
    all_players = Player.query.order_by(Player.username).all()
    return render_template('admin/players/index.html', players=all_players, form=form, create_open=True)


@admin_bp.route('/players/<int:player_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def player_edit(player_id):
    player = db.session.get(Player, player_id)
    if player is None:
        flash('Player not found.', 'error')
        return redirect(url_for('admin.players_index'))

    form = PlayerEditForm(obj=player)
    if form.validate_on_submit():
        # Check username uniqueness (excluding current player)
        existing = db.session.execute(
            select(Player).where(
                Player.username == form.username.data.strip(),
                Player.id != player_id,
            )
        ).scalar_one_or_none()
        if existing:
            flash(f'Username "{form.username.data}" is already taken.', 'error')
        else:
            player.username = form.username.data.strip()
            player.is_admin = form.is_admin.data
            player.yeargroup = (form.yeargroup.data or '').strip() or None
            new_pw = (form.new_password.data or '').strip()
            if new_pw:  # AD-33: blank = preserve existing hash
                player.set_password(new_pw)
            db.session.commit()
            flash(f'Player "{player.username}" updated.', 'success')
            return redirect(url_for('admin.players_index'))
    return render_template('admin/players/form.html', form=form, title='Edit Player', player=player)


@admin_bp.route('/players/<int:player_id>/delete', methods=['POST'])
@login_required
@admin_required
def player_delete(player_id):
    from app.models.game import RoundPlayer
    player = db.session.get(Player, player_id)
    if player is None:
        flash('Player not found.', 'error')
        return redirect(url_for('admin.players_index'))

    if RoundPlayer.query.filter_by(player_id=player_id).first():
        flash(
            f'Cannot delete "{player.username}" — they have participated in game sessions.',
            'error',
        )
        return redirect(url_for('admin.players_index'))

    username = player.username
    db.session.delete(player)
    db.session.commit()
    flash(f'Player "{username}" deleted.', 'success')
    return redirect(url_for('admin.players_index'))


# ── Groups ─────────────────────────────────────────────────────

@admin_bp.route('/groups/')
@login_required
@admin_required
def groups_index():
    all_groups = PlayerGroup.query.order_by(PlayerGroup.name).all()
    form = PlayerGroupForm()
    return render_template('admin/groups/index.html', groups=all_groups, form=form, create_open=False)


@admin_bp.route('/groups/new', methods=['GET', 'POST'])
@login_required
@admin_required
def group_new():
    form = PlayerGroupForm()
    if request.method == 'GET':
        all_groups = PlayerGroup.query.order_by(PlayerGroup.name).all()
        return render_template('admin/groups/index.html', groups=all_groups, form=form, create_open=True)
    if form.validate_on_submit():
        existing = PlayerGroup.query.filter_by(name=form.name.data.strip()).first()
        if existing:
            flash(f'Class "{form.name.data}" already exists.', 'error')
        else:
            group = PlayerGroup(
                name=form.name.data.strip(),
                description=(form.description.data or '').strip() or None,
            )
            db.session.add(group)
            db.session.commit()
            flash(f'Class "{group.name}" created. Add players below.', 'success')
            return redirect(url_for('admin.group_detail', group_id=group.id))
    all_groups = PlayerGroup.query.order_by(PlayerGroup.name).all()
    return render_template('admin/groups/index.html', groups=all_groups, form=form, create_open=True)


@admin_bp.route('/groups/<int:group_id>')
@login_required
@admin_required
def group_detail(group_id):
    group = db.session.get(PlayerGroup, group_id)
    if group is None:
        flash('Class not found.', 'error')
        return redirect(url_for('admin.groups_index'))

    members = group.members.order_by(Player.username).all()
    member_ids = {p.id for p in members}

    # Optional yeargroup filter for non-members
    yg_filter = request.args.get('yg', '').strip()

    non_member_q = Player.query.filter(~Player.id.in_(member_ids)) if member_ids \
        else Player.query
    if yg_filter:
        non_member_q = non_member_q.filter(Player.yeargroup == yg_filter)
    non_members = non_member_q.order_by(Player.yeargroup, Player.username).all()

    # All distinct yeargroups (for the filter dropdown)
    all_yeargroups = [
        r[0] for r in db.session.execute(
            db.select(Player.yeargroup)
            .where(Player.yeargroup.isnot(None))
            .distinct()
            .order_by(Player.yeargroup)
        ).all()
    ]

    return render_template(
        'admin/groups/detail.html',
        group=group,
        members=members,
        non_members=non_members,
        all_yeargroups=all_yeargroups,
        yg_filter=yg_filter,
    )


@admin_bp.route('/groups/<int:group_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def group_edit(group_id):
    group = db.session.get(PlayerGroup, group_id)
    if group is None:
        flash('Group not found.', 'error')
        return redirect(url_for('admin.groups_index'))

    form = PlayerGroupForm(obj=group)
    if form.validate_on_submit():
        existing = PlayerGroup.query.filter(
            PlayerGroup.name == form.name.data.strip(),
            PlayerGroup.id != group_id,
        ).first()
        if existing:
            flash(f'Class name "{form.name.data}" is already taken.', 'error')
        else:
            group.name = form.name.data.strip()
            group.description = (form.description.data or '').strip() or None
            db.session.commit()
            flash(f'Class "{group.name}" updated.', 'success')
            return redirect(url_for('admin.group_detail', group_id=group_id))
    return render_template('admin/groups/form.html', form=form, title='Edit Class', group=group)


@admin_bp.route('/groups/<int:group_id>/add_player', methods=['POST'])
@login_required
@admin_required
def group_add_player(group_id):
    group = db.session.get(PlayerGroup, group_id)
    if group is None:
        flash('Group not found.', 'error')
        return redirect(url_for('admin.groups_index'))

    player_id = request.form.get('player_id', type=int)
    player = db.session.get(Player, player_id) if player_id else None
    if player is None:
        flash('Player not found.', 'error')
    elif group.members.filter_by(id=player_id).first():
        flash(f'"{player.username}" is already in this class.', 'error')
    else:
        group.members.append(player)
        db.session.commit()
        flash(f'"{player.username}" added to class.', 'success')

    return redirect(url_for('admin.group_detail', group_id=group_id))


@admin_bp.route('/groups/<int:group_id>/remove_player/<int:player_id>', methods=['POST'])
@login_required
@admin_required
def group_remove_player(group_id, player_id):
    group = db.session.get(PlayerGroup, group_id)
    if group is None:
        flash('Group not found.', 'error')
        return redirect(url_for('admin.groups_index'))

    player = db.session.get(Player, player_id)
    if player and group.members.filter_by(id=player_id).first():
        group.members.remove(player)
        db.session.commit()
        flash(f'"{player.username}" removed from class.', 'success')
    else:
        flash('Player not found in this class.', 'error')

    return redirect(url_for('admin.group_detail', group_id=group_id))


@admin_bp.route('/groups/<int:group_id>/delete', methods=['POST'])
@login_required
@admin_required
def group_delete(group_id):
    group = db.session.get(PlayerGroup, group_id)
    if group is None:
        flash('Group not found.', 'error')
        return redirect(url_for('admin.groups_index'))

    in_use = GameSession.query.filter_by(group_id=group_id).first()
    if in_use:
        flash(
            f'Cannot delete class "{group.name}" — it is used by session #{in_use.id}.',
            'error',
        )
        return redirect(url_for('admin.groups_index'))

    name = group.name
    db.session.delete(group)
    db.session.commit()
    flash(f'Class "{name}" deleted.', 'success')
    return redirect(url_for('admin.groups_index'))


# ── Subjects ──────────────────────────────────────────────────────────────────

@admin_bp.route('/subjects/')
@login_required
@admin_required
def subjects_index():
    all_subjects = Subject.query.order_by(Subject.name).all()
    form = SubjectForm()
    return render_template('admin/subjects/index.html', subjects=all_subjects, form=form, create_open=False)


@admin_bp.route('/subjects/new', methods=['GET', 'POST'])
@login_required
@admin_required
def subject_new():
    form = SubjectForm()
    if request.method == 'GET':
        all_subjects = Subject.query.order_by(Subject.name).all()
        return render_template('admin/subjects/index.html', subjects=all_subjects, form=form, create_open=True)
    if form.validate_on_submit():
        name = form.name.data.strip()
        existing = Subject.query.filter(db.func.lower(Subject.name) == name.lower()).first()
        if existing:
            flash(f'Subject "{name}" already exists.', 'error')
        else:
            subject = Subject(
                name=name,
                description=(form.description.data or '').strip() or None,
            )
            db.session.add(subject)
            db.session.commit()
            flash(f'Subject "{subject.name}" created.', 'success')
            return redirect(url_for('admin.subjects_index'))
    all_subjects = Subject.query.order_by(Subject.name).all()
    return render_template('admin/subjects/index.html', subjects=all_subjects, form=form, create_open=True)


@admin_bp.route('/subjects/<int:subject_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def subject_edit(subject_id):
    subject = db.session.get(Subject, subject_id)
    if subject is None:
        flash('Subject not found.', 'error')
        return redirect(url_for('admin.subjects_index'))

    form = SubjectForm(obj=subject)
    if form.validate_on_submit():
        name = form.name.data.strip()
        existing = Subject.query.filter(
            db.func.lower(Subject.name) == name.lower(),
            Subject.id != subject_id,
        ).first()
        if existing:
            flash(f'Subject name "{name}" is already taken.', 'error')
        else:
            subject.name = name
            subject.description = (form.description.data or '').strip() or None
            db.session.commit()
            flash(f'Subject "{subject.name}" updated.', 'success')
            return redirect(url_for('admin.subjects_index'))
    return render_template('admin/subjects/form.html', form=form, title='Edit Subject', subject=subject)


@admin_bp.route('/subjects/<int:subject_id>/delete', methods=['POST'])
@login_required
@admin_required
def subject_delete(subject_id):
    subject = db.session.get(Subject, subject_id)
    if subject is None:
        flash('Subject not found.', 'error')
        return redirect(url_for('admin.subjects_index'))

    if subject.topics.count() > 0:
        flash(
            f'Cannot delete subject "{subject.name}" — '
            f'{subject.topics.count()} topic(s) reference it. Reassign them first.',
            'error',
        )
        return redirect(url_for('admin.subjects_index'))

    name = subject.name
    db.session.delete(subject)
    db.session.commit()
    flash(f'Subject "{name}" deleted.', 'success')
    return redirect(url_for('admin.subjects_index'))


# ── Analytics round viewer ─────────────────────────────────────────────────

def _answer_attempt_counts(round_id, *, problem_id=None):
    rows = AnalyticsAnswerAttempt.query.filter_by(round_id=round_id)
    if problem_id is not None:
        rows = rows.filter_by(problem_id=problem_id)
    attempts = rows.all()
    correct = sum(1 for attempt in attempts if attempt.is_correct)
    incorrect = len(attempts) - correct
    return {
        'attempts': len(attempts),
        'correct': correct,
        'incorrect': incorrect,
        'accuracy': (correct / len(attempts)) if attempts else None,
    }


def _build_analytics_problem_summaries(analytics_round):
    rows = (
        AnalyticsRoundProblem.query
        .filter_by(analytics_round_id=analytics_round.id)
        .order_by(AnalyticsRoundProblem.mode_context, AnalyticsRoundProblem.problem_title_snapshot, AnalyticsRoundProblem.problem_id)
        .all()
    )
    summaries = []
    for row in rows:
        player_problem_rows = AnalyticsPlayerProblem.query.filter_by(
            round_id=analytics_round.round_id,
            problem_id=row.problem_id,
            mode_context=row.mode_context,
        ).all()
        counts = _answer_attempt_counts(analytics_round.round_id, problem_id=row.problem_id)
        summaries.append({
            'row': row,
            'players_seen': sum(1 for item in player_problem_rows if item.first_seen_at is not None),
            'players_attempted': sum(1 for item in player_problem_rows if (item.attempt_count or 0) > 0),
            'players_solved': sum(1 for item in player_problem_rows if item.eventual_correct is True),
            'attempts': counts['attempts'],
            'correct': counts['correct'],
            'incorrect': counts['incorrect'],
            'accuracy': counts['accuracy'],
        })
    return summaries


def _analytics_csv_response(csv_data, filename):
    response = make_response(csv_data)
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _build_analytics_round_detail_context(analytics_round):
    player_rounds = (
        AnalyticsPlayerRound.query
        .filter_by(analytics_round_id=analytics_round.id)
        .order_by(AnalyticsPlayerRound.player_name_snapshot, AnalyticsPlayerRound.player_id)
        .all()
    )
    player_problems = (
        AnalyticsPlayerProblem.query
        .filter_by(analytics_round_id=analytics_round.id)
        .order_by(AnalyticsPlayerProblem.player_id, AnalyticsPlayerProblem.mode_context, AnalyticsPlayerProblem.problem_title_snapshot)
        .all()
    )
    answer_attempts = (
        AnalyticsAnswerAttempt.query
        .filter_by(analytics_round_id=analytics_round.id)
        .order_by(AnalyticsAnswerAttempt.submitted_at, AnalyticsAnswerAttempt.id)
        .all()
    )
    classic_events = []
    boss_events = []
    if analytics_round.mode == 'classic':
        classic_events = (
            AnalyticsClassicEconomyEvent.query
            .filter_by(analytics_round_id=analytics_round.id)
            .order_by(AnalyticsClassicEconomyEvent.occurred_at, AnalyticsClassicEconomyEvent.id)
            .all()
        )
    if analytics_round.mode == 'boss_rush':
        boss_events = (
            AnalyticsBossRushBattleEvent.query
            .filter_by(analytics_round_id=analytics_round.id)
            .order_by(AnalyticsBossRushBattleEvent.occurred_at, AnalyticsBossRushBattleEvent.id)
            .all()
        )
    return {
        'analytics_round': analytics_round,
        'player_rounds': player_rounds,
        'problem_summaries': _build_analytics_problem_summaries(analytics_round),
        'player_problems': player_problems,
        'answer_attempts': answer_attempts,
        'classic_events': classic_events,
        'boss_events': boss_events,
        'answer_counts': _answer_attempt_counts(analytics_round.round_id),
    }


@admin_bp.route('/analytics/')
@admin_bp.route('/analytics/rounds')
@login_required
@admin_required
def analytics_rounds():
    mode = (request.args.get('mode') or '').strip()
    q = AnalyticsRound.query
    if mode:
        q = q.filter_by(mode=mode)
    rounds = (
        q.order_by(
            AnalyticsRound.ended_at.desc().nullslast(),
            AnalyticsRound.started_at.desc().nullslast(),
            AnalyticsRound.id.desc(),
        )
        .limit(100)
        .all()
    )
    return render_template(
        'admin/analytics/index.html',
        rounds=rounds,
        selected_mode=mode,
    )


@admin_bp.route('/analytics/class-dashboard')
@login_required
@admin_required
def analytics_class_dashboard():
    groups = PlayerGroup.query.order_by(PlayerGroup.name).all()
    subjects = Subject.query.order_by(Subject.name).all()
    selected_group_id = request.args.get('group_id', type=int)
    selected_subject_id = request.args.get('subject_id', type=int)
    selected_mode = (request.args.get('mode') or '').strip()
    if selected_mode not in ('classic', 'boss_rush'):
        selected_mode = ''
    date_from_text = (request.args.get('date_from') or '').strip()
    date_to_text = (request.args.get('date_to') or '').strip()
    date_from = parse_date_filter(date_from_text)
    date_to = parse_date_filter(date_to_text, end=True)
    selected_group = db.session.get(PlayerGroup, selected_group_id) if selected_group_id else None
    dashboard = build_class_dashboard(
        selected_group.id,
        subject_id=selected_subject_id,
        mode=selected_mode,
        date_from=date_from,
        date_to=date_to,
    ) if selected_group else None
    return render_template(
        'admin/analytics/class_dashboard.html',
        groups=groups,
        subjects=subjects,
        selected_group=selected_group,
        selected_group_id=selected_group_id,
        selected_subject_id=selected_subject_id or 0,
        selected_mode=selected_mode,
        date_from_text=date_from_text,
        date_to_text=date_to_text,
        dashboard=dashboard,
        recent_groups=recent_groups_with_analytics(),
        export_args=request.args.to_dict(flat=True),
    )


@admin_bp.route('/analytics/class-dashboard/export.csv')
@login_required
@admin_required
def analytics_class_dashboard_export_csv():
    selected_group_id = request.args.get('group_id', type=int)
    selected_group = db.session.get(PlayerGroup, selected_group_id) if selected_group_id else None
    if selected_group is None:
        abort(404)

    selected_subject_id = request.args.get('subject_id', type=int)
    selected_mode = (request.args.get('mode') or '').strip()
    if selected_mode not in ('classic', 'boss_rush'):
        selected_mode = ''
    date_from_text = (request.args.get('date_from') or '').strip()
    date_to_text = (request.args.get('date_to') or '').strip()
    dashboard = build_class_dashboard(
        selected_group.id,
        subject_id=selected_subject_id,
        mode=selected_mode,
        date_from=parse_date_filter(date_from_text),
        date_to=parse_date_filter(date_to_text, end=True),
    )
    csv_data = build_class_dashboard_csv(
        selected_group,
        dashboard,
        filters={
            'subject_id': selected_subject_id,
            'mode': selected_mode,
            'date_from': date_from_text,
            'date_to': date_to_text,
        },
    )
    filename = analytics_class_dashboard_filename(
        selected_group,
        mode=selected_mode,
        subject_id=selected_subject_id,
    )
    return _analytics_csv_response(csv_data, filename)


@admin_bp.route('/analytics/rounds/<int:analytics_round_id>')
@login_required
@admin_required
def analytics_round_detail(analytics_round_id):
    analytics_round = db.session.get(AnalyticsRound, analytics_round_id)
    if analytics_round is None:
        abort(404)
    return render_template(
        'admin/analytics/round_detail.html',
        **_build_analytics_round_detail_context(analytics_round),
    )


@admin_bp.route('/analytics/rounds/<int:analytics_round_id>/export.csv')
@login_required
@admin_required
def analytics_round_detail_export_csv(analytics_round_id):
    analytics_round = db.session.get(AnalyticsRound, analytics_round_id)
    if analytics_round is None:
        abort(404)
    context = _build_analytics_round_detail_context(analytics_round)
    csv_data = build_round_detail_csv(**context)
    return _analytics_csv_response(csv_data, analytics_round_filename(analytics_round))


# ── History index + archive/delete/export controls ────────────────────────────────────────

@admin_bp.route('/history/rounds')
@login_required
@admin_required
def history_rounds():
    """Global index of all frozen rounds, newest first.

    Archived records are hidden by default.
    Pass ?include_archived=1 to reveal them.
    """
    include_archived = request.args.get('include_archived') == '1'
    q = RoundHistory.query
    if not include_archived:
        q = q.filter(RoundHistory.archived_at.is_(None))
    rounds = (
        q.order_by(RoundHistory.ended_at.desc(), RoundHistory.id.desc())
        .all()
    )
    round_ids = [rh.round_id for rh in rounds]
    analytics_by_round_id = {}
    if round_ids:
        analytics_by_round_id = {
            row.round_id: row
            for row in AnalyticsRound.query
            .filter(AnalyticsRound.round_id.in_(round_ids))
            .all()
        }
    return render_template(
        'admin/history/index.html',
        rounds=rounds,
        include_archived=include_archived,
        analytics_by_round_id=analytics_by_round_id,
    )


@admin_bp.route('/history/rounds/export')
@login_required
@admin_required
def history_rounds_export():
    """Download the global frozen round history index as a flat CSV.

    Visibility rules match the H2a index page:
    - default: archived rounds excluded
    - ?include_archived=1: archived rounds included
    """
    include_archived = request.args.get('include_archived') == '1'
    q = RoundHistory.query
    if not include_archived:
        q = q.filter(RoundHistory.archived_at.is_(None))
    rounds = (
        q.order_by(RoundHistory.ended_at.desc(), RoundHistory.id.desc())
        .all()
    )

    csv_data = build_history_csv(rounds)
    filename = 'round_history_export.csv'
    response = make_response(csv_data)
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@admin_bp.route('/history/rounds/<int:rh_id>/archive', methods=['POST'])
@login_required
@admin_required
def history_round_archive(rh_id):
    """Archive one frozen round history record (hide from default views)."""
    rh = db.session.get(RoundHistory, rh_id)
    if rh is None:
        abort(404)
    if rh.archived_at is None:
        rh.archived_at = datetime.now(timezone.utc)
        db.session.commit()
        flash(f'Round #{rh.round_number} archived.', 'success')
    referrer = request.referrer
    return redirect(referrer or url_for('admin.history_rounds'))


@admin_bp.route('/history/rounds/<int:rh_id>/unarchive', methods=['POST'])
@login_required
@admin_required
def history_round_unarchive(rh_id):
    """Unarchive one frozen round history record (restore to default views)."""
    rh = db.session.get(RoundHistory, rh_id)
    if rh is None:
        abort(404)
    if rh.archived_at is not None:
        rh.archived_at = None
        db.session.commit()
        flash(f'Round #{rh.round_number} unarchived.', 'success')
    referrer = request.referrer
    return redirect(referrer or url_for('admin.history_rounds'))


@admin_bp.route('/history/rounds/<int:rh_id>/delete', methods=['POST'])
@login_required
@admin_required
def history_round_delete(rh_id):
    """Permanently delete one frozen round history record.

    Child RoundPlayerResult rows are removed via ORM cascade='all, delete-orphan'.
    Live session/gameplay tables are not touched.
    """
    rh = db.session.get(RoundHistory, rh_id)
    if rh is None:
        abort(404)
    session_id = rh.session_id
    round_number = rh.round_number
    # ORM relationship has cascade='all, delete-orphan' — children deleted automatically
    db.session.delete(rh)
    db.session.commit()
    flash(f'Round #{round_number} history permanently deleted.', 'success')
    referrer = request.referrer
    return redirect(referrer or url_for('classic_admin.history', session_id=session_id))


# ── Diamonds — admin award flow (D1) ──────────────────────────────────────────

@admin_bp.route('/diamonds/')
@login_required
@admin_required
def diamonds_index():
    """Show all non-admin players with their current Diamonds balance."""
    players = Player.query.filter_by(is_admin=False).order_by(Player.username).all()

    # Build a {player_id: progression} map so the template can look up balances cheaply.
    player_ids = [p.id for p in players]
    progressions = (
        PlayerProgression.query
        .filter(PlayerProgression.player_id.in_(player_ids))
        .all()
    ) if player_ids else []
    prog_by_player = {pp.player_id: pp for pp in progressions}

    form = DiamondAwardForm()
    form.player_id.choices = [(p.id, p.username) for p in players]

    return render_template(
        'admin/diamonds/index.html',
        players=players,
        prog_by_player=prog_by_player,
        form=form,
    )


@admin_bp.route('/diamonds/award', methods=['POST'])
@login_required
@admin_required
def diamonds_award():
    """Award Diamonds to a single player.

    Atomic: both the balance update and the ledger entry are committed together,
    or neither is if an error occurs.
    """
    from flask_login import current_user

    players = Player.query.filter_by(is_admin=False).order_by(Player.username).all()
    form = DiamondAwardForm()
    form.player_id.choices = [(p.id, p.username) for p in players]

    if not form.validate_on_submit():
        # Validation failed — flash each error and redirect back.
        for field_errors in form.errors.values():
            for err in field_errors:
                flash(err, 'error')
        return redirect(url_for('admin.diamonds_index'))

    target_player = db.session.get(Player, form.player_id.data)
    if target_player is None or target_player.is_admin:
        flash('Invalid player selected.', 'error')
        return redirect(url_for('admin.diamonds_index'))

    try:
        new_balance = award_diamonds_to_player(
            player_id=target_player.id,
            amount=form.amount.data,
            reason=form.reason.data.strip(),
            admin_player_id=current_user.id,
        )
        db.session.commit()
        flash(
            f'Awarded {form.amount.data} Diamond(s) to "{target_player.username}". '
            f'New balance: {new_balance}.',
            'success',
        )
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')

    return redirect(url_for('admin.diamonds_index'))

