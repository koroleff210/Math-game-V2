import csv
import io
import json
import re
from datetime import datetime, timezone


def _format_dt(value):
    return value.strftime('%Y-%m-%d %H:%M:%S') if value else ''


def _format_pct(value):
    return '' if value is None else f'{value * 100:.1f}%'


def _format_bool(value):
    if value is True:
        return 'yes'
    if value is False:
        return 'no'
    return ''


def _format_json(value):
    if value in (None, '', [], {}):
        return ''
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _safe_filename_part(value, fallback):
    text = str(value or fallback).strip()
    text = re.sub(r'[^A-Za-z0-9._-]+', '_', text)
    return text.strip('._-') or fallback


def _today_text():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _section(writer, title, headers=None):
    writer.writerow([])
    writer.writerow([title])
    if headers:
        writer.writerow(headers)


def _csv_text(write_func):
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    write_func(writer)
    return '\ufeff' + buffer.getvalue()


def analytics_class_dashboard_filename(group, *, mode=None, subject_id=None):
    group_part = _safe_filename_part(getattr(group, 'name', None), f'class_{getattr(group, "id", "unknown")}')
    mode_part = _safe_filename_part(mode or 'all_modes', 'all_modes')
    subject_part = f'_subject_{subject_id}' if subject_id else ''
    return f'analytics_class_{group_part}_{mode_part}{subject_part}_{_today_text()}.csv'


def analytics_round_filename(analytics_round):
    mode_part = _safe_filename_part(getattr(analytics_round, 'mode', None), 'round')
    return f'analytics_round_{analytics_round.id}_{mode_part}_{_today_text()}.csv'


def build_class_dashboard_csv(group, dashboard, *, filters=None):
    filters = filters or {}

    def write(writer):
        writer.writerow(['Class Analytics Export'])
        writer.writerow(['class_id', getattr(group, 'id', '')])
        writer.writerow(['class_name', getattr(group, 'name', '')])
        writer.writerow(['subject_id', filters.get('subject_id') or ''])
        writer.writerow(['mode', filters.get('mode') or 'all'])
        writer.writerow(['date_from', filters.get('date_from') or ''])
        writer.writerow(['date_to', filters.get('date_to') or ''])
        writer.writerow(['generated_at', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')])

        overview = dashboard.get('overview', {})
        _section(writer, 'Overview')
        for label, key in [
            ('rounds', 'round_count'),
            ('players', 'player_count'),
            ('answer_attempts', 'attempts'),
            ('correct_attempts', 'correct'),
            ('incorrect_attempts', 'incorrect'),
        ]:
            writer.writerow([label, overview.get(key, 0)])
        writer.writerow(['overall_accuracy', _format_pct(overview.get('accuracy'))])
        writer.writerow(['first_try_correct', _format_pct(overview.get('first_try_accuracy'))])

        _section(writer, 'Topic Summary', [
            'subject', 'topic', 'players', 'problems', 'attempts', 'correct_attempts',
            'incorrect_attempts', 'accuracy', 'first_try_correct', 'eventual_correct',
            'linked_rounds_count', 'linked_analytics_round_ids',
        ])
        for row in dashboard.get('topic_rows', []):
            writer.writerow([
                row.get('subject_name') or 'n/a',
                row.get('topic_name') or 'Unassigned',
                row.get('players', 0),
                row.get('problems', 0),
                row.get('attempts', 0),
                row.get('correct', 0),
                row.get('incorrect', 0),
                _format_pct(row.get('accuracy')),
                _format_pct(row.get('first_try_accuracy')),
                _format_pct(row.get('eventual_correct_pct')),
                row.get('round_count', 0),
                ','.join(str(r.id) for r in row.get('rounds', [])),
            ])

        _section(writer, 'Player Summary', [
            'player_id', 'player_name', 'rounds_played', 'problems_seen',
            'problems_attempted', 'problems_solved', 'attempts', 'correct_attempts',
            'incorrect_attempts', 'accuracy', 'first_try_correct', 'classic_gold_net',
            'boss_rush_damage', 'boss_rush_max_combo', 'linked_analytics_round_ids',
        ])
        for row in dashboard.get('player_rows', []):
            writer.writerow([
                row.get('player_id'),
                row.get('player_name'),
                row.get('rounds_played', 0),
                row.get('problems_seen', 0),
                row.get('problems_attempted', 0),
                row.get('problems_solved', 0),
                row.get('attempts', 0),
                row.get('correct', 0),
                row.get('incorrect', 0),
                _format_pct(row.get('accuracy')),
                _format_pct(row.get('first_try_accuracy')),
                row.get('classic_gold_net', 0),
                row.get('boss_rush_damage', 0),
                row.get('boss_rush_max_combo', 0),
                ','.join(str(r.id) for r in row.get('rounds', [])),
            ])

        _section(writer, 'Most Missed Problems', [
            'problem_id', 'problem_title', 'topic', 'mode_context', 'players_seen',
            'attempts', 'correct_attempts', 'incorrect_attempts', 'accuracy',
            'most_common_wrong_option', 'wrong_option_count', 'linked_analytics_round_ids',
        ])
        for row in dashboard.get('missed_problem_rows', []):
            wrong = row.get('most_common_wrong_option') or {}
            wrong_label = ''
            if wrong:
                wrong_label = f'{wrong.get("label") or ""}: {wrong.get("text") or ""}'.strip()
            writer.writerow([
                row.get('problem_id'),
                row.get('problem_title'),
                row.get('topic_name') or 'Unassigned',
                row.get('mode_context'),
                row.get('players_seen', 0),
                row.get('attempts', 0),
                row.get('correct', 0),
                row.get('incorrect', 0),
                _format_pct(row.get('accuracy')),
                wrong_label,
                wrong.get('count', ''),
                ','.join(str(r.id) for r in row.get('rounds', [])),
            ])

        _section(writer, 'Recent Rounds', [
            'analytics_round_id', 'game_round_id', 'date', 'mode', 'problem_set',
            'attempts', 'correct_attempts', 'incorrect_attempts', 'accuracy',
        ])
        for item in dashboard.get('recent_rounds', []):
            row = item.get('round')
            writer.writerow([
                row.id,
                row.round_id,
                _format_dt(row.ended_at or row.started_at),
                row.mode,
                row.problem_set_name_snapshot or '',
                item.get('attempts', 0),
                item.get('correct', 0),
                item.get('incorrect', 0),
                _format_pct(item.get('accuracy')),
            ])

    return _csv_text(write)


def build_round_detail_csv(
    analytics_round,
    *,
    player_rounds,
    problem_summaries,
    player_problems,
    answer_attempts,
    classic_events,
    boss_events,
    answer_counts,
):
    def write(writer):
        writer.writerow(['Analytics Round Export'])
        _section(writer, 'Round Metadata')
        for label, value in [
            ('analytics_round_id', analytics_round.id),
            ('session_id', analytics_round.session_id),
            ('game_round_id', analytics_round.round_id),
            ('round_number', analytics_round.round_number),
            ('mode', analytics_round.mode),
            ('session_label', analytics_round.session_label_snapshot),
            ('class', analytics_round.group_name_snapshot),
            ('subject', analytics_round.subject_name_snapshot),
            ('problem_set', analytics_round.problem_set_name_snapshot),
            ('started_at', _format_dt(analytics_round.started_at)),
            ('ended_at', _format_dt(analytics_round.ended_at)),
            ('finalized_at', _format_dt(analytics_round.finalized_at)),
            ('answer_attempts', answer_counts.get('attempts', 0)),
            ('correct_attempts', answer_counts.get('correct', 0)),
            ('incorrect_attempts', answer_counts.get('incorrect', 0)),
            ('accuracy', _format_pct(answer_counts.get('accuracy'))),
        ]:
            writer.writerow([label, value or ''])

        _section(writer, 'Player Summaries', [
            'player_id', 'player_name', 'problems_seen', 'problems_attempted',
            'problems_solved', 'correct_attempts', 'incorrect_attempts',
            'first_try_correct', 'accuracy', 'gold_start', 'gold_end',
            'gems_start', 'gems_end', 'gold_net', 'gems_net', 'damage_dealt',
            'max_combo', 'final_combo', 'hp_final', 'diamonds_awarded', 'summary_json',
        ])
        for row in player_rounds:
            writer.writerow([
                row.player_id,
                row.player_name_snapshot or '',
                row.problems_seen,
                row.problems_attempted,
                row.problems_solved,
                row.correct_attempts,
                row.incorrect_attempts,
                row.first_try_correct_count,
                _format_pct(row.accuracy),
                row.gold_start,
                row.gold_end,
                row.gems_start,
                row.gems_end,
                row.gold_net,
                row.gems_net,
                row.damage_dealt,
                row.max_combo,
                row.final_combo,
                row.hp_final,
                row.diamonds_awarded,
                _format_json(row.summary_json),
            ])

        _section(writer, 'Problem Summaries', [
            'problem_id', 'problem_title', 'mode_context', 'subject', 'topic',
            'players_seen', 'players_attempted', 'players_solved', 'attempts',
            'correct_attempts', 'incorrect_attempts', 'accuracy',
        ])
        for item in problem_summaries:
            row = item['row']
            writer.writerow([
                row.problem_id,
                row.problem_title_snapshot or '',
                row.mode_context,
                row.subject_name_snapshot or '',
                row.topic_name_snapshot or '',
                item.get('players_seen', 0),
                item.get('players_attempted', 0),
                item.get('players_solved', 0),
                item.get('attempts', 0),
                item.get('correct', 0),
                item.get('incorrect', 0),
                _format_pct(item.get('accuracy')),
            ])

        _section(writer, 'Player Problem Lifecycle', [
            'player_id', 'problem_id', 'problem_title', 'mode_context', 'status',
            'attempt_count', 'first_attempt_correct', 'eventual_correct',
            'first_seen_at', 'completed_at',
        ])
        for row in player_problems:
            writer.writerow([
                row.player_id,
                row.problem_id,
                row.problem_title_snapshot or '',
                row.mode_context,
                row.status,
                row.attempt_count,
                _format_bool(row.first_attempt_correct),
                _format_bool(row.eventual_correct),
                _format_dt(row.first_seen_at),
                _format_dt(row.completed_at),
            ])

        _section(writer, 'Answer Attempts', [
            'submitted_at', 'player_id', 'problem_id', 'mode_context',
            'action_context', 'attempt_number', 'submitted_answer_text',
            'selected_option_id', 'selected_option_label', 'selected_option_text',
            'is_correct', 'extra_json',
        ])
        for row in answer_attempts:
            writer.writerow([
                _format_dt(row.submitted_at),
                row.player_id,
                row.problem_id,
                row.mode_context,
                row.action_context or '',
                row.attempt_number,
                row.submitted_answer_text or '',
                row.selected_option_id or '',
                row.selected_option_label_snapshot or '',
                row.selected_option_text_snapshot or '',
                _format_bool(row.is_correct),
                _format_json(row.extra_json),
            ])

        if analytics_round.mode == 'classic':
            _section(writer, 'Classic Economy Events', [
                'occurred_at', 'event_type', 'actor_player_id', 'actor_name',
                'target_player_id', 'target_name', 'problem_id',
                'linked_answer_attempt_id', 'gold_delta_actor', 'gold_delta_target',
                'gems_delta_actor', 'gems_delta_target', 'actor_gold_after',
                'target_gold_after', 'item_key', 'bonus_key', 'details_json',
            ])
            for row in classic_events:
                writer.writerow([
                    _format_dt(row.occurred_at),
                    row.event_type,
                    row.actor_player_id,
                    row.actor_name_snapshot or '',
                    row.target_player_id or '',
                    row.target_name_snapshot or '',
                    row.problem_id or row.linked_problem_id or '',
                    row.linked_answer_attempt_id or '',
                    row.gold_delta_actor,
                    row.gold_delta_target,
                    row.gems_delta_actor,
                    row.gems_delta_target,
                    row.actor_gold_after,
                    row.target_gold_after,
                    row.item_key or '',
                    row.bonus_key or '',
                    _format_json(row.details_json),
                ])

        if analytics_round.mode == 'boss_rush':
            _section(writer, 'Boss Rush Battle Events', [
                'occurred_at', 'event_type', 'player_id', 'player_name',
                'target_player_id', 'boss_type', 'boss_hp_before', 'boss_hp_after',
                'player_hp_before', 'player_hp_after', 'combo_before',
                'combo_after', 'damage_intended', 'damage_applied',
                'shield_or_guard_absorbed', 'ability_key', 'ability_count',
                'linked_answer_attempt_id', 'linked_boss_rush_attempt_id',
                'linked_problem_id', 'details_json',
            ])
            for row in boss_events:
                writer.writerow([
                    _format_dt(row.occurred_at),
                    row.event_type,
                    row.player_id or '',
                    row.player_name_snapshot or '',
                    row.target_player_id or '',
                    row.boss_type or '',
                    row.boss_hp_before,
                    row.boss_hp_after,
                    row.player_hp_before,
                    row.player_hp_after,
                    row.combo_before,
                    row.combo_after,
                    row.damage_intended,
                    row.damage_applied,
                    row.shield_or_guard_absorbed,
                    row.ability_key or '',
                    row.ability_count or '',
                    row.linked_answer_attempt_id or '',
                    row.linked_boss_rush_attempt_id or '',
                    row.linked_problem_id or '',
                    _format_json(row.details_json),
                ])

    return _csv_text(write)
