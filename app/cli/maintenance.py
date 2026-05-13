# app/cli/maintenance.py
#
# Maintenance CLI commands for local/dev use.
#
# COMMANDS
# --------
#   python -m flask pilot-reset --dry-run
#       Show exactly what would be deleted. No DB changes.
#
#   python -m flask pilot-reset --apply --yes
#       Create a timestamped SQLite backup, then delete all session/gameplay
#       data and problem-bank content.  Players, Groups, and memberships are
#       preserved.
#
#   python -m flask fresh-start --dry-run
#       Show everything that would be wiped and re-seeded. No DB changes.
#
#   python -m flask fresh-start --yes
#       Create a timestamped SQLite backup, wipe ALL data (including players,
#       groups, diamonds, upgrades), then seed a minimal test dataset.
#
#       Seeded accounts:
#           admin   / admin123   (is_admin=True)
#           player1 / player123
#           player2 / player123
#           player3 / player123
#
#       Seeded problem bank:
#           Subject: "Mathematics"
#           Topics:  "Arithmetic", "Basic Algebra"
#           Problems: 8 simple questions (4 per topic)
#           Problem Set: "Test Pack" containing all 8 problems
#
#       Seeded class:
#           "Test Class" — player1, player2, player3
#
# DELETION SCOPE (pilot-reset)
# --------------
# DELETE (session / gameplay):
#   player_inventory, steal_event, store_item, player_wallet,
#   player_classic_state, player_problem_state, problem_solver_count,
#   classic_round_config, player_answer, round_player_result, round_history,
#   game_round, round_player, session_participant_snapshot, game_session
#
# DELETE (problem bank):
#   problem_set_problems (association), problem_set, problem, topic, subject
#
# PRESERVE (pilot-reset):
#   player, player_group, player_group_members, alembic_version
#
# DELETION SCOPE (fresh-start, full wipe)
# ----------------------------------------
# Everything above PLUS:
#   diamond_transaction, player_progression,
#   player_upgrade, gear_item_definition, player_gear_ownership,
#   player_gear_loadout, player_group_members, player_group, player

import os
import shutil
import json
import re
from datetime import datetime, timezone

import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import text

from app.extensions import db
from app.models.classic import (
    ClassicRoundConfig,
    PlayerClassicState,
    PlayerInventory,
    PlayerProblemState,
    PlayerWallet,
    ProblemSolverCount,
    StealEvent,
    StoreItem,
)
from app.models.game import GameRound, GameSession, PlayerAnswer, RoundPlayer
from app.models.gear import GearItemDefinition, PlayerGearLoadout, PlayerGearOwnership
from app.models.groups import PlayerGroup
from app.models.history import RoundHistory, RoundPlayerResult
from app.models.player import Player
from app.models.problems import (
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    PROBLEM_ANSWER_TYPE_TEXT_INPUT,
    PROBLEM_BLOCK_TYPE_RICH_TEXT,
    Problem,
    ProblemAcceptedAnswer,
    ProblemBlock,
    ProblemChoiceOption,
    ProblemSet,
    Topic,
    problem_set_problems,
)
from app.models.progression import (
    DiamondTransaction,
    PlayerProgression,
    PlayerUpgrade,
    SessionParticipantSnapshot,
)
from app.models.subjects import Subject
from app.services.gear import ensure_sample_gear_items
from app.services.problem_content import sync_problem_legacy_compat_fields


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_path():
    """Resolve the absolute path to the SQLite DB file.

    Works for URI patterns like:
      sqlite:///math_game.db   → <instance_path>/math_game.db
      sqlite:////abs/path.db   → /abs/path.db
    Raises RuntimeError if the database is not SQLite.
    """
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not uri.startswith('sqlite:'):
        raise RuntimeError(
            f'Database does not appear to be SQLite (URI: {uri!r}). '
            'pilot-reset only supports SQLite. Aborting.'
        )
    # sqlite:///relative  → relative to instance folder
    # sqlite:////absolute → absolute path
    if uri.startswith('sqlite:////'):
        # Four slashes = absolute path
        return uri[len('sqlite:///'):]
    # Three slashes = relative to instance folder
    rel = uri[len('sqlite:///'):]
    return os.path.join(current_app.instance_path, rel)


def _backup_db(db_path: str) -> str:
    """Copy the DB to <instance>/backups/math_game_YYYYMMDD_HHMMSS.db.
    Returns the backup file path.  Creates the backups/ dir if needed.
    """
    backups_dir = os.path.join(current_app.instance_path, 'backups')
    os.makedirs(backups_dir, exist_ok=True)
    base = os.path.basename(db_path)
    stem, ext = os.path.splitext(base)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    backup_name = f'{stem}_backup_{ts}{ext}'
    backup_path = os.path.join(backups_dir, backup_name)
    shutil.copy2(db_path, backup_path)
    return backup_path


def _collect_counts() -> dict:
    """Return a dict of {table_name: row_count} for all tables in scope."""
    tables = {
        # session / gameplay
        'player_inventory':     PlayerInventory,
        'steal_event':          StealEvent,
        'store_item':           StoreItem,
        'player_wallet':        PlayerWallet,
        'player_classic_state': PlayerClassicState,
        'player_problem_state': PlayerProblemState,
        'problem_solver_count': ProblemSolverCount,
        'classic_round_config': ClassicRoundConfig,
        'player_answer':        PlayerAnswer,
        'round_player_result':  RoundPlayerResult,
        'round_history':        RoundHistory,
        'game_round':                    GameRound,
        'round_player':                  RoundPlayer,
        'session_participant_snapshot':   SessionParticipantSnapshot,
        'game_session':                  GameSession,
        # problem bank
        'problem_set':          ProblemSet,
        'problem':              Problem,
        'topic':                Topic,
        'subject':              Subject,
    }
    counts = {}
    for name, model in tables.items():
        counts[name] = db.session.execute(
            text(f'SELECT COUNT(*) FROM {model.__tablename__}')
        ).scalar()

    # association table (no ORM class)
    counts['problem_set_problems'] = db.session.execute(
        text('SELECT COUNT(*) FROM problem_set_problems')
    ).scalar()

    # preserved tables (for reporting only)
    counts['_player']               = db.session.execute(text('SELECT COUNT(*) FROM player')).scalar()
    counts['_player_group']         = db.session.execute(text('SELECT COUNT(*) FROM player_group')).scalar()
    counts['_player_group_members'] = db.session.execute(text('SELECT COUNT(*) FROM player_group_members')).scalar()

    return counts


def _print_counts(counts: dict, label: str) -> None:
    click.echo(f'\n{"-"*52}')
    click.echo(f'  {label}')
    click.echo(f'{"-"*52}')

    click.echo('\n  DELETE SCOPE - session / gameplay data:')
    session_tables = [
        'player_inventory', 'steal_event', 'store_item',
        'player_wallet', 'player_classic_state', 'player_problem_state',
        'problem_solver_count', 'classic_round_config', 'player_answer',
        'round_player_result', 'round_history',
        'game_round', 'round_player', 'session_participant_snapshot', 'game_session',
    ]
    for t in session_tables:
        click.echo(f'    {t:<28} {counts.get(t, "?"):>6} rows')

    click.echo('\n  DELETE SCOPE - problem-bank data:')
    bank_tables = [
        'problem_set_problems', 'problem_set', 'problem', 'topic', 'subject',
    ]
    for t in bank_tables:
        click.echo(f'    {t:<28} {counts.get(t, "?"):>6} rows')

    click.echo('\n  PRESERVE:')
    preserve = [
        ('player',               counts.get('_player', '?')),
        ('player_group',         counts.get('_player_group', '?')),
        ('player_group_members', counts.get('_player_group_members', '?')),
    ]
    for name, cnt in preserve:
        click.echo(f'    {name:<28} {cnt:>6} rows  (kept)')

    click.echo(f'{"-"*52}\n')


def _do_delete() -> None:
    """Execute all deletions in FK-safe order inside the current session.
    Caller is responsible for commit/rollback.
    """
    # 1. Deepest dependents first.
    #    PlayerInventory references StoreItem → delete before StoreItem.
    db.session.execute(text('DELETE FROM player_inventory'))

    # 2. StealEvent references game_session, game_round, player
    db.session.execute(text('DELETE FROM steal_event'))

    # 3. StoreItem references game_session
    db.session.execute(text('DELETE FROM store_item'))

    # 4. PlayerWallet references player, game_session
    db.session.execute(text('DELETE FROM player_wallet'))

    # 5. PlayerClassicState references player, game_session
    db.session.execute(text('DELETE FROM player_classic_state'))

    # 6. PlayerProblemState references player, game_round, problem
    db.session.execute(text('DELETE FROM player_problem_state'))

    # 7. ProblemSolverCount references game_round, problem
    db.session.execute(text('DELETE FROM problem_solver_count'))

    # 8. ClassicRoundConfig references game_round
    db.session.execute(text('DELETE FROM classic_round_config'))

    # 9. PlayerAnswer references game_round, player
    db.session.execute(text('DELETE FROM player_answer'))

    # 10. RoundPlayerResult references round_history and player
    db.session.execute(text('DELETE FROM round_player_result'))

    # 11. RoundHistory references game_round and game_session
    db.session.execute(text('DELETE FROM round_history'))

    # 12. GameRound references game_session (+ nullable problem FK)
    db.session.execute(text('DELETE FROM game_round'))

    # 13. RoundPlayer references game_session, player
    db.session.execute(text('DELETE FROM round_player'))

    # 14. SessionParticipantSnapshot references game_session, player
    db.session.execute(text('DELETE FROM session_participant_snapshot'))

    # 15. GameSession (top-level; all dependents deleted)
    db.session.execute(text('DELETE FROM game_session'))

    # --- problem bank ---

    # 13. problem_set_problems association table
    db.session.execute(text('DELETE FROM problem_set_problems'))

    # 14. ProblemSet
    db.session.execute(text('DELETE FROM problem_set'))

    # 15. Problem (GameRound.problem_id nullable; rounds already gone)
    db.session.execute(text('DELETE FROM problem'))

    # 16. Topic (problems already gone)
    db.session.execute(text('DELETE FROM topic'))

    # 17. Subject (topics already gone)
    db.session.execute(text('DELETE FROM subject'))


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

@click.command('pilot-reset')
@click.option('--dry-run', 'mode', flag_value='dry', default=True,
              help='Show what would be deleted without making any changes (default).')
@click.option('--apply',   'mode', flag_value='apply',
              help='Perform the actual deletion (requires --yes).')
@click.option('--yes', is_flag=True, default=False,
              help='Confirm destructive deletion when using --apply.')
@with_appcontext
def pilot_reset_command(mode: str, yes: bool) -> None:
    """Safe pilot-data cleanup: removes sessions, gameplay history, and
    problem-bank content.  Players, Groups, and memberships are preserved.

    Default (and --dry-run): prints counts only; no DB changes.

    --apply --yes: creates a timestamped SQLite backup, then deletes.
    """
    click.echo('\n===  PILOT RESET  ===')

    # ── Validate flags ─────────────────────────────────────────────────────
    if mode == 'apply' and not yes:
        click.echo(
            '\n  ERROR: --apply requires --yes to confirm destructive deletion.\n'
            '  Usage:  python -m flask pilot-reset --apply --yes\n',
            err=True,
        )
        raise SystemExit(1)

    # ── Collect before-counts ──────────────────────────────────────────────
    try:
        before = _collect_counts()
    except Exception as exc:
        click.echo(f'\n  ERROR collecting counts: {exc}', err=True)
        raise SystemExit(1)

    _print_counts(before, 'COUNTS BEFORE (what will be deleted)')

    if mode == 'dry':
        click.echo('  DRY-RUN complete - no changes made.')
        click.echo('  To apply: python -m flask pilot-reset --apply --yes\n')
        return

    # ── Apply mode ─────────────────────────────────────────────────────────
    # 1. Locate and verify DB file
    try:
        db_path = _db_path()
    except RuntimeError as exc:
        click.echo(f'\n  {exc}', err=True)
        raise SystemExit(1)

    if not os.path.isfile(db_path):
        click.echo(
            f'\n  ERROR: SQLite DB file not found at expected path:\n'
            f'    {db_path}\n'
            '  Cannot create backup; aborting.',
            err=True,
        )
        raise SystemExit(1)

    # 2. Create backup
    try:
        backup_path = _backup_db(db_path)
    except Exception as exc:
        click.echo(f'\n  ERROR creating backup: {exc}', err=True)
        raise SystemExit(1)

    click.echo(f'  Backup created: {backup_path}')

    # 3. Delete
    click.echo('  Deleting data...')
    try:
        _do_delete()
        db.session.commit()
        click.echo('  Deletion committed successfully.')
    except Exception as exc:
        db.session.rollback()
        click.echo(f'\n  ERROR during deletion; transaction rolled back.\n  {exc}', err=True)
        raise SystemExit(1)

    # 4. After-counts
    try:
        after = _collect_counts()
    except Exception as exc:
        click.echo(f'\n  Warning: could not collect after-counts: {exc}', err=True)
        return

    _print_counts(after, 'COUNTS AFTER (verification)')

    # 5. Final summary
    click.echo('  [OK] Pilot reset complete.')
    click.echo(f'  Backup:  {backup_path}')
    click.echo(f'  Players: {after["_player"]} rows preserved.')
    click.echo(f'  Groups:  {after["_player_group"]} rows preserved.')
    click.echo()


# ---------------------------------------------------------------------------
# fresh-start: wipe everything + re-seed a minimal test dataset
# ---------------------------------------------------------------------------

_SEED_USERS = [
    {'username': 'admin',   'password': 'admin123',  'is_admin': True},
    {'username': 'player1', 'password': 'player123', 'is_admin': False},
    {'username': 'player2', 'password': 'player123', 'is_admin': False},
    {'username': 'player3', 'password': 'player123', 'is_admin': False},
]

_SEED_SUBJECT = 'Mathematics'

_SEED_TOPICS = [
    {'name': 'Arithmetic',   'description': 'Basic addition, subtraction, multiplication and division'},
    {'name': 'Basic Algebra', 'description': 'Simple one-variable equations'},
]

# (topic_index, title, prompt, answer, difficulty)
_SEED_PROBLEMS = [
    (0, 'Arithmetic Q1', 'What is 7 + 8?',    '15', 1),
    (0, 'Arithmetic Q2', 'What is 12 − 5?',   '7',  1),
    (0, 'Arithmetic Q3', 'What is 6 × 4?',    '24', 1),
    (0, 'Arithmetic Q4', 'What is 20 ÷ 4?',   '5',  1),
    (1, 'Algebra Q1',    'Solve for x:  x + 3 = 10',  '7',  2),
    (1, 'Algebra Q2',    'Solve for x:  2x = 14',     '7',  2),
    (1, 'Algebra Q3',    'Solve for x:  x − 4 = 9',   '13', 2),
    (1, 'Algebra Q4',    'Solve for x:  3x = 21',     '7',  2),
]

_SEED_PROBLEM_SET_NAME = 'Test Pack'
_SEED_PROBLEM_SET_DESC = 'Minimal problem bank for manual gameplay testing'

_SEED_GROUP = {'name': 'Test Class', 'description': 'Default class for manual gameplay testing'}


def _collect_full_counts() -> dict:
    """Row counts for every table that fresh-start touches."""
    counts = {}
    simple = {
        # progression
        'diamond_transaction':    'diamond_transaction',
        'player_upgrade':         'player_upgrade',
        'player_progression':     'player_progression',
        'gear_item_definition':   'gear_item_definition',
        'player_gear_ownership':  'player_gear_ownership',
        'player_gear_loadout':    'player_gear_loadout',
        # session / gameplay (already in pilot-reset)
        'player_inventory':       'player_inventory',
        'steal_event':            'steal_event',
        'store_item':             'store_item',
        'player_wallet':          'player_wallet',
        'player_classic_state':   'player_classic_state',
        'player_problem_state':   'player_problem_state',
        'problem_solver_count':   'problem_solver_count',
        'classic_round_config':   'classic_round_config',
        'player_answer':          'player_answer',
        'round_player_result':    'round_player_result',
        'round_history':          'round_history',
        'game_round':             'game_round',
        'round_player':           'round_player',
        'session_participant_snapshot': 'session_participant_snapshot',
        'game_session':           'game_session',
        # problem bank
        'problem_set_problems':   'problem_set_problems',
        'problem_set':            'problem_set',
        'problem':                'problem',
        'topic':                  'topic',
        'subject':                'subject',
        # players / groups
        'player_group_members':   'player_group_members',
        'player_group':           'player_group',
        'player':                 'player',
    }
    for key, tbl in simple.items():
        counts[key] = db.session.execute(text(f'SELECT COUNT(*) FROM {tbl}')).scalar()
    return counts


def _print_full_counts(counts: dict, label: str) -> None:
    click.echo(f'\n{"-"*56}')
    click.echo(f'  {label}')
    click.echo(f'{"-"*56}')

    sections = [
        ('WIPE - progression', [
            'diamond_transaction',
            'player_upgrade', 'player_progression',
            'player_gear_ownership', 'player_gear_loadout', 'gear_item_definition',
        ]),
        ('WIPE - session / gameplay', [
            'player_inventory', 'steal_event', 'store_item',
            'player_wallet', 'player_classic_state', 'player_problem_state',
            'problem_solver_count', 'classic_round_config', 'player_answer',
            'round_player_result', 'round_history',
            'game_round', 'round_player', 'session_participant_snapshot', 'game_session',
        ]),
        ('WIPE - problem bank', [
            'problem_set_problems', 'problem_set', 'problem', 'topic', 'subject',
        ]),
        ('WIPE - players / groups', [
            'player_group_members', 'player_group', 'player',
        ]),
    ]
    for section_label, keys in sections:
        click.echo(f'\n  {section_label}:')
        for k in keys:
            click.echo(f'    {k:<32} {counts.get(k, "?"):>6} rows')
    click.echo(f'{"-"*56}\n')


def _do_full_wipe() -> None:
    """Delete all data in FK-safe order.  Caller commits or rolls back."""

    # 1. Deepest session dependents
    db.session.execute(text('DELETE FROM player_inventory'))
    db.session.execute(text('DELETE FROM steal_event'))
    db.session.execute(text('DELETE FROM store_item'))
    db.session.execute(text('DELETE FROM player_wallet'))
    db.session.execute(text('DELETE FROM player_classic_state'))
    db.session.execute(text('DELETE FROM player_problem_state'))
    db.session.execute(text('DELETE FROM problem_solver_count'))
    db.session.execute(text('DELETE FROM classic_round_config'))
    db.session.execute(text('DELETE FROM player_answer'))
    db.session.execute(text('DELETE FROM round_player_result'))
    db.session.execute(text('DELETE FROM round_history'))

    db.session.execute(text('DELETE FROM game_round'))
    db.session.execute(text('DELETE FROM round_player'))

    # session_participant_snapshot references game_session → delete before game_session
    db.session.execute(text('DELETE FROM session_participant_snapshot'))

    # diamond_transaction references game_session → delete before game_session
    db.session.execute(text('DELETE FROM diamond_transaction'))

    db.session.execute(text('DELETE FROM game_session'))

    # Problem bank
    db.session.execute(text('DELETE FROM problem_set_problems'))
    db.session.execute(text('DELETE FROM problem_set'))
    db.session.execute(text('DELETE FROM problem'))
    db.session.execute(text('DELETE FROM topic'))
    db.session.execute(text('DELETE FROM subject'))

    # Progression (references player → before player)
    db.session.execute(text('DELETE FROM player_gear_ownership'))
    db.session.execute(text('DELETE FROM player_gear_loadout'))
    db.session.execute(text('DELETE FROM gear_item_definition'))
    db.session.execute(text('DELETE FROM player_upgrade'))
    db.session.execute(text('DELETE FROM player_progression'))

    # Groups / players
    db.session.execute(text('DELETE FROM player_group_members'))
    db.session.execute(text('DELETE FROM player_group'))
    db.session.execute(text('DELETE FROM player'))


def _seed_structured_problem(
    *,
    topic_id: int,
    title: str,
    prompt: str,
    difficulty: int,
    accepted_answers: list[str] | None = None,
    choice_options: list[tuple[str, bool]] | None = None,
) -> Problem:
    """Create a seeded problem through the canonical structured content path."""
    answer_type = (
        PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE
        if choice_options is not None
        else PROBLEM_ANSWER_TYPE_TEXT_INPUT
    )
    problem = Problem(
        topic_id=topic_id,
        title=title,
        prompt_text='',
        answer_text='',
        answer_type=answer_type,
        difficulty=difficulty,
    )
    db.session.add(problem)
    db.session.flush()

    db.session.add(
        ProblemBlock(
            problem_id=problem.id,
            position=1,
            block_type=PROBLEM_BLOCK_TYPE_RICH_TEXT,
            text_content=prompt,
        )
    )

    if answer_type == PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE:
        if not choice_options:
            raise ValueError('Seeded multiple-choice problems require choice options.')
        correct_count = sum(1 for _, is_correct in choice_options if is_correct)
        if correct_count != 1:
            raise ValueError('Seeded multiple-choice problems must have exactly one correct option.')
        for position, (option_text, is_correct) in enumerate(choice_options, start=1):
            db.session.add(
                ProblemChoiceOption(
                    problem_id=problem.id,
                    position=position,
                    option_text=option_text,
                    is_correct=is_correct,
                )
            )
    else:
        cleaned_answers = [(answer or '').strip() for answer in (accepted_answers or []) if (answer or '').strip()]
        if not cleaned_answers:
            raise ValueError('Seeded text-input problems require at least one accepted answer.')
        for position, answer_text in enumerate(cleaned_answers, start=1):
            db.session.add(
                ProblemAcceptedAnswer(
                    problem_id=problem.id,
                    position=position,
                    answer_text=answer_text,
                )
            )

    db.session.flush()
    sync_problem_legacy_compat_fields(problem)
    return problem


def _do_seed() -> dict:
    """Seed minimal test data.  Returns a summary dict."""
    # ── Players ───────────────────────────────────────────────────────────────
    for u in _SEED_USERS:
        p = Player(username=u['username'], is_admin=u['is_admin'])
        p.set_password(u['password'])
        db.session.add(p)
    db.session.flush()

    # ── Subject ───────────────────────────────────────────────────────────────
    subject = Subject(name=_SEED_SUBJECT)
    db.session.add(subject)
    db.session.flush()

    # ── Topics ────────────────────────────────────────────────────────────────
    topics = []
    for td in _SEED_TOPICS:
        t = Topic(name=td['name'], description=td['description'], subject_id=subject.id)
        db.session.add(t)
        topics.append(t)
    db.session.flush()

    # ── Problems ──────────────────────────────────────────────────────────────
    problems = []
    for (topic_idx, title, prompt, answer, diff) in _SEED_PROBLEMS:
        pr = _seed_structured_problem(
            topic_id=topics[topic_idx].id,
            title=title,
            prompt=prompt,
            difficulty=diff,
            accepted_answers=[answer],
        )
        problems.append(pr)
    db.session.flush()

    # ── Problem Set ───────────────────────────────────────────────────────────
    ps = ProblemSet(name=_SEED_PROBLEM_SET_NAME, description=_SEED_PROBLEM_SET_DESC)
    ps.problems.extend(problems)
    db.session.add(ps)

    # ── Group (class) ─────────────────────────────────────────────────────────
    group = PlayerGroup(name=_SEED_GROUP['name'],
                        description=_SEED_GROUP['description'])
    db.session.add(group)
    db.session.flush()

    student_players = Player.query.filter(
        Player.username.in_(['player1', 'player2', 'player3'])
    ).all()
    for sp in student_players:
        group.members.append(sp)

    ensure_sample_gear_items()
    player1 = Player.query.filter_by(username='player1').first()
    if player1 is not None:
        for item_id in ['bronze_pickaxe', 'oak_buckler', 'lucky_coin']:
            db.session.add(PlayerGearOwnership(player_id=player1.id, item_id=item_id))
        db.session.flush()
        db.session.add(
            PlayerGearLoadout(
                player_id=player1.id,
                main_hand_item_id='bronze_pickaxe',
                off_hand_item_id='oak_buckler',
                pocket1_item_id='lucky_coin',
            )
        )

    return {
        'players':      len(_SEED_USERS),
        'subjects':     1,
        'topics':       len(_SEED_TOPICS),
        'problems':     len(_SEED_PROBLEMS),
        'problem_sets': 1,
        'groups':       1,
        'gear_items':   GearItemDefinition.query.count(),
    }


@click.command('fresh-start')
@click.option('--dry-run', 'mode', flag_value='dry', default=True,
              help='Show what would be wiped and re-seeded (default, no changes).')
@click.option('--yes', 'mode', flag_value='apply',
              help='Wipe all data, create backup, then seed minimal test dataset.')
@with_appcontext
def fresh_start_command(mode: str) -> None:
    """Full wipe + minimal re-seed for manual gameplay testing.

    Destroys ALL rows in every table (including players, diamonds, upgrades)
    then creates a minimal test dataset.

    Default (--dry-run): prints counts only, no changes.
    --yes: creates a timestamped SQLite backup, wipes, seeds.

    Seeded accounts:
      admin / admin123 (admin)  |  player1-3 / player123

    Seeded problem bank:
      Subject: Mathematics  |  Topics: Arithmetic, Basic Algebra
      Problems: 8  |  Problem Set: "Test Pack"

    Seeded class:
      "Test Class" — player1, player2, player3

    Seeded gear:
      Sample persistent gear catalog + starter ownership/loadout for player1
    """
    click.echo('\n===  FRESH START  ===')

    try:
        before = _collect_full_counts()
    except Exception as exc:
        click.echo(f'\n  ERROR collecting counts: {exc}', err=True)
        raise SystemExit(1)

    _print_full_counts(before, 'CURRENT DB STATE (will be fully wiped)')

    if mode == 'dry':
        click.echo('  DRY-RUN: no changes made.')
        click.echo('  To apply: python -m flask fresh-start --yes\n')
        return

    # ── Backup ────────────────────────────────────────────────────────────────
    try:
        db_path = _db_path()
    except RuntimeError as exc:
        click.echo(f'\n  {exc}', err=True)
        raise SystemExit(1)

    if not os.path.isfile(db_path):
        click.echo(
            f'\n  WARNING: SQLite DB not found at {db_path!r}. '
            'Skipping backup (DB may not exist yet).',
        )
        backup_path = None
    else:
        try:
            backup_path = _backup_db(db_path)
            click.echo(f'  Backup created: {backup_path}')
        except Exception as exc:
            click.echo(f'\n  ERROR creating backup: {exc}', err=True)
            raise SystemExit(1)

    # ── Wipe ──────────────────────────────────────────────────────────────────
    click.echo('  Wiping all data...')
    try:
        _do_full_wipe()
        db.session.flush()
    except Exception as exc:
        db.session.rollback()
        click.echo(f'\n  ERROR during wipe; rolled back.\n  {exc}', err=True)
        raise SystemExit(1)

    # ── Seed ──────────────────────────────────────────────────────────────────
    click.echo('  Seeding minimal test data...')
    try:
        summary = _do_seed()
        db.session.commit()
        click.echo('  Seed committed successfully.')
    except Exception as exc:
        db.session.rollback()
        click.echo(f'\n  ERROR during seed; rolled back.\n  {exc}', err=True)
        raise SystemExit(1)

    # ── After-counts ──────────────────────────────────────────────────────────
    try:
        after = _collect_full_counts()
        _print_full_counts(after, 'DB STATE AFTER (verification)')
    except Exception as exc:
        click.echo(f'\n  Warning: could not collect after-counts: {exc}', err=True)

    # ── Summary ───────────────────────────────────────────────────────────────
    click.echo('  [OK] Fresh start complete.')
    if backup_path:
        click.echo(f'  Backup:       {backup_path}')
    click.echo(f'  Players:      {summary["players"]} seeded')
    click.echo(f'  Subject:      {summary["subjects"]}  (Mathematics)')
    click.echo(f'  Topics:       {summary["topics"]}  (Arithmetic, Basic Algebra)')
    click.echo(f'  Problems:     {summary["problems"]} seeded')
    click.echo(f'  Problem sets: {summary["problem_sets"]}  (Test Pack)')
    click.echo(f'  Groups:       {summary["groups"]}  (Test Class)')
    click.echo(f'  Gear items:   {summary["gear_items"]} seeded')
    click.echo()
    click.echo('  Login credentials:')
    click.echo('    admin   / admin123   (admin)')
    click.echo('    player1 / player123')
    click.echo('    player2 / player123')
    click.echo('    player3 / player123')
    click.echo()
    click.echo('  Class: "Test Class" → player1, player2, player3')
    click.echo()

def _copy_if_missing(src: str, dst: str) -> tuple[bool, str]:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        return False, 'collision'
    shutil.copy2(src, dst)
    return True, 'copied'


def _legacy_flat_files_for_slot(slot_dir: str) -> list[str]:
    files = []
    if not os.path.isdir(slot_dir):
        return files
    for name in sorted(os.listdir(slot_dir), key=str.lower):
        full = os.path.join(slot_dir, name)
        if not os.path.isfile(full):
            continue
        if os.path.splitext(name)[1].lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            continue
        files.append(name)
    return files


@click.command('migrate-gear-assets')
@click.option('--apply', is_flag=True, default=False, help='Actually copy files into package folders.')
@click.option('--dry-run', is_flag=True, default=False, help='Alias for default behavior; report only and do not copy files.')
@with_appcontext
def migrate_gear_assets_command(apply: bool, dry_run: bool) -> None:
    """Copy legacy flat gear assets into package folder structure (copy-only)."""
    dry_mode = (not apply) or dry_run
    static_root = current_app.static_folder
    gear_root = os.path.join(static_root, 'gear')
    report = {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'dry_run': dry_mode,
        'applied': not dry_mode,
        'entries': [],
        'collisions': [],
        'skipped': [],
    }

    slot_variant_default = {
        'chest': 'm',
        'boots': 'm',
        'head': 'm',
        'main_hand': 'm',
        'off_hand': 'm',
        'pocket': 'm',
    }

    head_back = {}
    head_front = {}
    chest_front = {}
    chest_underlay = {}

    for slot in sorted(slot_variant_default.keys()):
        slot_dir = os.path.join(gear_root, slot)
        for filename in _legacy_flat_files_for_slot(slot_dir):
            lowered = filename.lower()
            src = os.path.join(slot_dir, filename)

            if slot == 'head':
                m = re.match(r'^head_(?P<key>.+)(?P<part>[ab])\.png$', lowered)
                if not m:
                    report['skipped'].append({'slot': slot, 'old_path': src, 'reason': 'not_head_pair_pattern'})
                    continue
                key = m.group('key')
                if m.group('part') == 'a':
                    head_front[key] = filename
                else:
                    head_back[key] = filename
                continue

            if slot == 'chest':
                if lowered == 'body_upper.png':
                    report['skipped'].append({'slot': slot, 'old_path': src, 'reason': 'base_body_file'})
                    continue
                m_under = re.match(r'^chest_(?P<key>.+)a\.png$', lowered)
                if m_under:
                    chest_underlay[m_under.group('key')] = filename
                    continue
                m_front = re.match(r'^chest_(?P<key>.+)\.png$', lowered)
                if m_front:
                    chest_front[m_front.group('key')] = filename
                    continue
                report['skipped'].append({'slot': slot, 'old_path': src, 'reason': 'not_chest_pattern'})
                continue

            if slot == 'boots':
                if lowered == 'body_lower.png':
                    report['skipped'].append({'slot': slot, 'old_path': src, 'reason': 'base_body_file'})
                    continue
                m = re.match(r'^boots_(?P<key>.+)\.png$', lowered)
                if not m:
                    report['skipped'].append({'slot': slot, 'old_path': src, 'reason': 'not_boots_pattern'})
                    continue
                key = m.group('key')
                dst = os.path.join(slot_dir, key, 'm', 'front.png')
                if dry_mode:
                    status = 'would_copy'
                else:
                    copied, status = _copy_if_missing(src, dst)
                    if not copied and status == 'collision':
                        report['collisions'].append({'old_path': src, 'new_path': dst, 'slot': slot, 'package_key': key, 'variant': 'm', 'layer_role': 'front'})
                report['entries'].append({'old_path': src, 'new_path': dst, 'slot': slot, 'package_key': key, 'variant': 'm', 'layer_role': 'front', 'status': status})
                continue

            if slot in {'main_hand', 'off_hand'}:
                if slot == 'off_hand' and lowered == 'off_hand_base.png':
                    report['skipped'].append({'slot': slot, 'old_path': src, 'reason': 'off_hand_base'})
                    continue
                prefix = f'{slot}_'
                m = re.match(rf'^{re.escape(prefix)}(?P<key>.+)\.png$', lowered)
                if not m:
                    report['skipped'].append({'slot': slot, 'old_path': src, 'reason': 'not_slot_pattern'})
                    continue
                key = m.group('key')
                dst = os.path.join(slot_dir, key, 'm', 'front.png')
                if dry_mode:
                    status = 'would_copy'
                else:
                    copied, status = _copy_if_missing(src, dst)
                    if not copied and status == 'collision':
                        report['collisions'].append({'old_path': src, 'new_path': dst, 'slot': slot, 'package_key': key, 'variant': 'm', 'layer_role': 'front'})
                report['entries'].append({'old_path': src, 'new_path': dst, 'slot': slot, 'package_key': key, 'variant': 'm', 'layer_role': 'front', 'status': status})

    for key in sorted(set(head_back.keys()) | set(head_front.keys())):
        back_name = head_back.get(key)
        front_name = head_front.get(key)
        if not back_name or not front_name:
            report['skipped'].append({'slot': 'head', 'package_key': key, 'reason': 'incomplete_head_pair'})
            continue
        for role, source_name in (('back', back_name), ('front', front_name)):
            src = os.path.join(gear_root, 'head', source_name)
            dst = os.path.join(gear_root, 'head', key, 'm', f'{role}.png')
            if dry_mode:
                status = 'would_copy'
            else:
                copied, status = _copy_if_missing(src, dst)
                if not copied and status == 'collision':
                    report['collisions'].append({'old_path': src, 'new_path': dst, 'slot': 'head', 'package_key': key, 'variant': 'm', 'layer_role': role})
            report['entries'].append({'old_path': src, 'new_path': dst, 'slot': 'head', 'package_key': key, 'variant': 'm', 'layer_role': role, 'paired_assets_detected': True, 'status': status})

    for key in sorted(chest_front.keys()):
        src_front = os.path.join(gear_root, 'chest', chest_front[key])
        dst_front = os.path.join(gear_root, 'chest', key, 'm', 'front.png')
        if dry_mode:
            status = 'would_copy'
        else:
            copied, status = _copy_if_missing(src_front, dst_front)
            if not copied and status == 'collision':
                report['collisions'].append({'old_path': src_front, 'new_path': dst_front, 'slot': 'chest', 'package_key': key, 'variant': 'm', 'layer_role': 'front'})
        report['entries'].append({'old_path': src_front, 'new_path': dst_front, 'slot': 'chest', 'package_key': key, 'variant': 'm', 'layer_role': 'front', 'paired_assets_detected': key in chest_underlay, 'status': status})

        under = chest_underlay.get(key)
        if under:
            src_under = os.path.join(gear_root, 'chest', under)
            dst_under = os.path.join(gear_root, 'chest', key, 'm', 'underlay.png')
            if dry_mode:
                status_under = 'would_copy'
            else:
                copied, status_under = _copy_if_missing(src_under, dst_under)
                if not copied and status_under == 'collision':
                    report['collisions'].append({'old_path': src_under, 'new_path': dst_under, 'slot': 'chest', 'package_key': key, 'variant': 'm', 'layer_role': 'underlay'})
            report['entries'].append({'old_path': src_under, 'new_path': dst_under, 'slot': 'chest', 'package_key': key, 'variant': 'm', 'layer_role': 'underlay', 'paired_assets_detected': True, 'status': status_under})

    reports_dir = os.path.join(current_app.instance_path, 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(
        reports_dir,
        f'gear_asset_migration_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.json',
    )
    with open(report_path, 'w', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
        handle.write('\n')

    click.echo('Gear asset migration scan complete.')
    if dry_mode:
        click.echo('  mode: dry-run (no files copied)')
    else:
        click.echo('  mode: apply (copy enabled)')
    click.echo(f'  dry_run: {dry_mode}')
    click.echo(f'  entries: {len(report["entries"])}')
    click.echo(f'  collisions: {len(report["collisions"])}')
    click.echo(f'  skipped: {len(report["skipped"])}')
    click.echo(f'  report: {report_path}')


@click.command('audit-legacy-gear-keys')
@with_appcontext
def audit_legacy_gear_keys_command() -> None:
    """Report active gear definitions still pointing to legacy flat image_key values."""
    static_root = current_app.static_folder
    rows = (
        GearItemDefinition.query
        .filter(GearItemDefinition.is_active.is_(True))
        .order_by(GearItemDefinition.slot_type, GearItemDefinition.id)
        .all()
    )

    legacy = []
    for item in rows:
        image_key = (item.image_key or '').strip()
        if not image_key:
            continue
        package_dir = os.path.join(static_root, 'gear', item.slot_type, image_key)
        if os.path.isdir(package_dir):
            continue
        legacy.append({
            'id': item.id,
            'slot_type': item.slot_type,
            'image_key': image_key,
        })

    click.echo('Legacy image_key audit complete.')
    click.echo(f'  active_items: {len(rows)}')
    click.echo(f'  legacy_image_key_items: {len(legacy)}')
    if legacy:
        click.echo('  items:')
        for item in legacy:
            click.echo(f"    - {item['id']} ({item['slot_type']}): {item['image_key']}")


@click.command('migrate-gear-image-keys-to-packages')
@click.option('--apply', is_flag=True, default=False, help='Apply DB updates. Default is report-only.')
@with_appcontext
def migrate_gear_image_keys_to_packages_command(apply: bool) -> None:
    """Migrate specific active gear image_key values from legacy flat filenames to package keys."""
    static_root = current_app.static_folder
    dry_run = not apply
    targets = [
        {'id': 'boots', 'slot_type': 'boots', 'old_image_key': 'boots_008.png', 'new_image_key': '008', 'avatar_asset_key': '008'},
        {'id': 'chest001', 'slot_type': 'chest', 'old_image_key': 'chest_007.png', 'new_image_key': '007', 'avatar_asset_key': '007'},
        {'id': 'robe002', 'slot_type': 'chest', 'old_image_key': 'chest_004.png', 'new_image_key': '004', 'avatar_asset_key': '004'},
        {'id': 'head1', 'slot_type': 'head', 'old_image_key': 'head_001a.png', 'new_image_key': '001', 'avatar_asset_key': '001'},
        {'id': 'Main002', 'slot_type': 'main_hand', 'old_image_key': 'main_hand_006.png', 'new_image_key': '006', 'avatar_asset_key': '006'},
        {'id': 'main hand', 'slot_type': 'main_hand', 'old_image_key': 'main_hand_001.png', 'new_image_key': '001', 'avatar_asset_key': '001'},
        {'id': 'off002', 'slot_type': 'off_hand', 'old_image_key': 'off_hand_002.png', 'new_image_key': '002', 'avatar_asset_key': '002'},
        {'id': 'off1', 'slot_type': 'off_hand', 'old_image_key': 'off_hand_005.png', 'new_image_key': '005', 'avatar_asset_key': '005'},
    ]

    report = {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'dry_run': dry_run,
        'rows': [],
        'updated_count': 0,
        'skipped_count': 0,
        'error_count': 0,
    }

    for spec in targets:
        row = {
            'id': spec['id'],
            'slot_type': spec['slot_type'],
            'expected_old_image_key': spec['old_image_key'],
            'new_image_key': spec['new_image_key'],
            'status': None,
            'notes': [],
        }
        item = db.session.get(GearItemDefinition, spec['id'])
        if item is None:
            row['status'] = 'missing_row'
            row['notes'].append('GearItemDefinition row not found.')
            report['error_count'] += 1
            report['rows'].append(row)
            continue

        row['name'] = item.name
        row['is_active'] = bool(item.is_active)
        row['current_image_key'] = item.image_key
        row['current_avatar_asset_key'] = item.avatar_asset_key

        if item.slot_type != spec['slot_type']:
            row['status'] = 'slot_mismatch'
            row['notes'].append(f"Found slot_type={item.slot_type!r}, expected {spec['slot_type']!r}.")
            report['error_count'] += 1
            report['rows'].append(row)
            continue

        pkg_dir = os.path.join(static_root, 'gear', spec['slot_type'], spec['new_image_key'])
        m_dir = os.path.join(pkg_dir, 'm')
        f_dir = os.path.join(pkg_dir, 'f')
        has_m = os.path.isdir(m_dir) and any(name.lower().endswith('.png') for name in os.listdir(m_dir))
        has_f = os.path.isdir(f_dir) and any(name.lower().endswith('.png') for name in os.listdir(f_dir))
        row['package_dir'] = pkg_dir
        row['has_m_assets'] = has_m
        row['has_f_assets'] = has_f

        if not has_m or not has_f:
            row['status'] = 'missing_package_assets'
            if not has_m:
                row['notes'].append('Missing m package assets.')
            if not has_f:
                row['notes'].append('Missing f package assets.')
            report['skipped_count'] += 1
            report['rows'].append(row)
            continue

        if item.image_key == spec['new_image_key']:
            row['status'] = 'already_migrated'
            report['skipped_count'] += 1
            report['rows'].append(row)
            continue

        if item.image_key != spec['old_image_key']:
            row['status'] = 'unexpected_current_image_key'
            row['notes'].append(f"Current image_key is {item.image_key!r}, expected {spec['old_image_key']!r}.")
            report['skipped_count'] += 1
            report['rows'].append(row)
            continue

        if dry_run:
            row['status'] = 'would_update'
            report['rows'].append(row)
            continue

        item.image_key = spec['new_image_key']
        row['status'] = 'updated'
        report['updated_count'] += 1
        report['rows'].append(row)

    if not dry_run:
        db.session.commit()

    reports_dir = os.path.join(current_app.instance_path, 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(
        reports_dir,
        f'gear_image_key_migration_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.json',
    )
    with open(report_path, 'w', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
        handle.write('\n')

    click.echo('Gear image_key migration report complete.')
    click.echo(f'  dry_run: {dry_run}')
    click.echo(f'  updated: {report["updated_count"]}')
    click.echo(f'  skipped: {report["skipped_count"]}')
    click.echo(f'  errors: {report["error_count"]}')
    click.echo(f'  report: {report_path}')
