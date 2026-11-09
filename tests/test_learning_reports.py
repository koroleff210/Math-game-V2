"""Run directly: .venv/Scripts/python.exe tests/test_learning_reports.py.

Uses in-memory SQLite and temporary media; production records are never used.
"""
import csv
from datetime import datetime, timezone
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.extensions import db
from app.models.analytics import AnalyticsRoundProblem, AnalyticsSessionSettings, AnalyticsPlayerProblem
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.groups import PlayerGroup
from app.models.player import Player
from app.models.problems import Problem, Topic, ProblemChoiceOption, ProblemBlock
from app.services.analytics import (ensure_player_round, record_answer_attempt, snapshot_round_problem,
                                    finalize_round_summary, ensure_player_problem)
from app.services.learning_reports import build_session_report, report_payload
from app.services.learning_exports import evidence_zip
from app.services.analytics_reports import build_player_dashboard, build_class_dashboard


class Config:
    TESTING = True
    SECRET_KEY = 'learning-report-isolated-test'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SOCKETIO_ASYNC_MODE = 'threading'
    WTF_CSRF_ENABLED = False
    SHARED_IDENTITY_URL = ''


class LearningReportTests(unittest.TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.app = create_app(Config)
        self.app.config['MEDIA_ROOT'] = self.media.name
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.admin = Player(username='teacher', password_hash='unused', is_admin=True)
        self.a = Player(username='Alice-private-name', password_hash='unused')
        self.b = Player(username='Bob-private-name', password_hash='unused')
        self.outsider = Player(username='outsider', password_hash='unused')
        self.group = PlayerGroup(name='Y12')
        self.group.members.extend([self.a, self.b])
        topic = Topic(name='Forces')
        self.problem = Problem(topic=topic, title='Vector components', prompt_text='A 10 N vector at 60 degrees. Horizontal component?', answer_text='', answer_type='multiple_choice', difficulty=2)
        db.session.add_all([self.admin, self.a, self.b, self.outsider, self.group, self.problem])
        db.session.flush()
        self.options = [ProblemChoiceOption(problem_id=self.problem.id, position=1, option_text='5 N', is_correct=True),
                        ProblemChoiceOption(problem_id=self.problem.id, position=2, option_text='8.7 N', is_correct=False)]
        db.session.add_all(self.options)
        self.session = GameSession(mode='boss_rush', status='active', label='Forces lesson', group=self.group)
        db.session.add(self.session)
        db.session.flush()
        self.round = GameRound(session_id=self.session.id, round_number=1, started_at=datetime.now(timezone.utc))
        db.session.add(self.round)
        db.session.flush()
        db.session.add_all([RoundPlayer(session_id=self.session.id, player_id=p.id) for p in (self.a, self.b)])
        ensure_player_round(self.round, self.a)
        ensure_player_round(self.round, self.b)
        snapshot_round_problem(self.round, self.problem, 'boss_rush_attack')
        snapshot_round_problem(self.round, self.problem, 'boss_rush_recovery')
        self.answer(self.a, False)
        self.answer(self.a, True)
        self.answer(self.a, False, 'boss_rush_recovery')
        ensure_player_problem(self.round, self.b, self.problem, 'boss_rush_attack', mark_seen=True)
        db.session.commit()
        self.client = self.app.test_client()
        self.login(self.admin)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.media.cleanup()

    def login(self, player):
        from flask import g
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session.clear()
            session['_user_id'] = str(player.id)
            session['_fresh'] = True

    def answer(self, player, correct, context='boss_rush_attack', text=None):
        return record_answer_attempt(self.round, player, self.problem, is_correct=correct,
            selected_option_id=self.options[0 if correct else 1].id, submitted_answer_text=text, mode_context=context)

    def finish(self):
        self.round.ended_at = datetime.now(timezone.utc)
        self.session.status = 'finished'
        finalize_round_summary(self.round)
        db.session.commit()

    def publish(self):
        self.finish()
        return self.client.post(f'/admin/analytics/sessions/{self.session.id}/settings', data={'action':'publish'})

    def test_metrics_and_contexts(self):
        r = build_session_report(self.session)
        self.assertEqual(r['metrics']['attempted'], 2)
        self.assertEqual(r['metrics']['first_correct'], 0)
        self.assertEqual(r['metrics']['solved'], 1)
        self.assertEqual(r['metrics']['submissions'], 3)
        self.assertEqual(r['questions'][0]['metrics']['submissions'], 2)
        self.assertEqual(r['questions'][1]['metrics']['submissions'], 1)
        self.assertEqual([c['state'] for c in r['students'][0]['cells']], ['retry_correct','incorrect'])
        self.assertEqual([c['state'] for c in r['students'][1]['cells']], ['unanswered','unseen'])

    def test_existing_round_context_defect(self):
        from app.routes.admin import _build_analytics_problem_summaries
        rows = _build_analytics_problem_summaries(self.round.analytics_round if hasattr(self.round,'analytics_round') else self._ar())
        self.assertEqual([r['attempts'] for r in rows], [2,1])

    def _ar(self):
        from app.models.analytics import AnalyticsRound
        return AnalyticsRound.query.filter_by(round_id=self.round.id).one()

    def test_snapshot_preserved_after_edit(self):
        old = snapshot_round_problem(self.round,self.problem,'boss_rush_attack').content_snapshot_json
        self.problem.prompt_text = 'Changed prompt'
        self.options[0].option_text = 'Changed answer'
        self.options[0].is_correct = False
        db.session.flush()
        again = snapshot_round_problem(self.round,self.problem,'boss_rush_attack').content_snapshot_json
        self.assertEqual(old, again)
        self.assertIn('10 N', again['body']['blocks'][0]['text_content'])
        self.assertEqual(again['choices']['options'][0]['option_text'], '5 N')
        self.assertEqual(again['answer_key']['correct_option_ids'], [self.options[0].id])

    def test_edit_guard_for_unfinished_round(self):
        path=f'/admin/problems/{self.problem.id}/blocks/add'
        self.assertEqual(self.client.post(path,data={}).status_code,409)
        self.finish()
        self.assertNotEqual(self.client.post(path,data={}).status_code,409)

    def test_teacher_pages_and_scope(self):
        for path in ['/admin/analytics/sessions', f'/admin/analytics/sessions/{self.session.id}',
                     f'/admin/analytics/sessions/{self.session.id}?student={self.a.id}&context=boss_rush_recovery',
                     f'/admin/analytics/sessions?student={self.a.id}', '/admin/analytics/sessions?page=2']:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200, path)
        self.assertEqual(self.client.get(f'/admin/analytics/sessions/{self.session.id}?student=oops').status_code,400)

    def test_publish_only_after_finished(self):
        path=f'/admin/analytics/sessions/{self.session.id}/settings'
        self.assertEqual(self.client.post(path,data={'action':'publish'}).status_code,400)
        self.assertEqual(self.publish().status_code,302)
        self.assertIsNotNone(db.session.get(AnalyticsSessionSettings,self.session.id).published_at)

    def test_student_permissions_and_withdraw(self):
        self.login(self.a)
        path=f'/player/learning/sessions/{self.session.id}'
        self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.get('/admin/analytics/sessions').status_code,403)
        self.login(self.admin)
        self.publish()
        self.login(self.a)
        html=self.client.get(path).get_data(as_text=True)
        self.assertIn('Your results',html)
        self.assertNotIn(self.b.username,html)
        self.assertEqual(self.client.get(f'/admin/analytics/sessions/{self.session.id}/export.zip').status_code,403)
        self.login(self.outsider)
        self.assertEqual(self.client.get(path).status_code,404)
        self.login(self.admin)
        self.client.post(f'/admin/analytics/sessions/{self.session.id}/settings',data={'action':'withdraw'})
        self.login(self.a)
        self.assertEqual(self.client.get(path).status_code,404)

    def test_progress_hides_private_sessions(self):
        self.assertEqual(build_player_dashboard(self.a.id)['overview']['correct'],0)
        self.publish()
        self.assertEqual(build_player_dashboard(self.a.id)['overview']['correct'],1)

    def test_exclusions_consistent(self):
        path=f'/admin/analytics/sessions/{self.session.id}/settings'
        self.assertEqual(self.client.post(path,data={'action':'save'}).status_code,400)
        self.publish()
        self.assertEqual(self.client.post(path,data={'action':'save','exclusion_reason':'Connection interrupted'}).status_code,302)
        self.assertEqual(build_player_dashboard(self.a.id)['overview']['correct'],0)
        self.assertEqual(build_class_dashboard(self.group.id)['overview']['attempts'],0)
        self.assertEqual(build_session_report(self.session)['metrics']['submissions'],3)

    def test_export_aliases_scope_and_content(self):
        settings=db.session.get(AnalyticsSessionSettings,self.session.id)
        settings.teacher_notes='PRIVATE TEACHER NOTE'
        archive=ZipFile(evidence_zip(build_session_report(self.session,player_id=self.a.id,mode_context='boss_rush_attack')))
        payload=json.loads(archive.read('report.json'))
        self.assertEqual(len(payload['students']),1)
        self.assertEqual(len(payload['questions']),1)
        self.assertEqual(payload['metrics']['submissions'],2)
        self.assertEqual(payload['questions'][0]['content']['answer_key']['correct_option_ids'],[self.options[0].id])
        text=archive.read('report.json').decode()
        for private in (self.a.username,self.b.username,'PRIVATE TEACHER NOTE','source_bank_path','password'):
            self.assertNotIn(private,text)
        self.assertIn('ANALYSIS_PROMPT.txt',archive.namelist())

    def test_csv_formula_escaping(self):
        self.answer(self.a,False,text='=1+1')
        db.session.flush()
        archive=ZipFile(evidence_zip(build_session_report(self.session)))
        rows=list(csv.DictReader(StringIO(archive.read('attempts.csv').decode('utf-8-sig'))))
        self.assertIn("'=1+1", [row['answer_text'] for row in rows])

    def test_legacy_content_not_replaced(self):
        snapshot=AnalyticsRoundProblem.query.first()
        snapshot.content_snapshot_json=None
        db.session.flush()
        r=build_session_report(self.session)
        self.assertFalse(r['questions'][0]['content_available'])
        self.assertIsNone(r['questions'][0]['content'])

    def test_multi_round_and_scope(self):
        other=GameRound(session_id=self.session.id,round_number=2,started_at=datetime.now(timezone.utc))
        db.session.add(other)
        db.session.flush()
        ensure_player_round(other,self.a)
        record_answer_attempt(other,self.a,self.problem,is_correct=True,mode_context='boss_rush_attack')
        db.session.flush()
        r=build_session_report(self.session)
        self.assertEqual(len(r['questions']),3)
        self.assertEqual(r['metrics']['attempted'],3)
        self.assertEqual(r['metrics']['first_correct'],1)
        scoped=build_session_report(self.session,round_id=other.id)
        self.assertEqual(scoped['metrics']['submissions'],1)

    def test_roster_remains_after_membership_change(self):
        self.group.members.remove(self.b)
        db.session.flush()
        settings=db.session.get(AnalyticsSessionSettings,self.session.id)
        self.assertIn(self.b.id,[r['player_id'] for r in settings.roster_snapshot_json])

    def test_images_are_frozen_and_exported(self):
        from PIL import Image
        from app.models.media import UploadedAsset
        source=Path(self.media.name)/'original.png'
        Image.new('RGB',(4,4),'red').save(source)
        asset=UploadedAsset(category='problem',display_name='diagram',storage_name=source.name,media_type='image/png',sha256='test')
        db.session.add(asset)
        db.session.flush()
        db.session.add(ProblemBlock(problem_id=self.problem.id,position=1,block_type='image',image_path=f'uploaded:{asset.id}',image_width_pct=100))
        db.session.flush()
        other=GameRound(session_id=self.session.id,round_number=2)
        db.session.add(other)
        db.session.flush()
        snap=snapshot_round_problem(other,self.problem,'boss_rush_attack')
        name=snap.content_snapshot_json['body']['blocks'][0]['asset_name']
        self.assertTrue(name)
        original=source.read_bytes()
        source.unlink()
        archive=ZipFile(evidence_zip(build_session_report(self.session)))
        self.assertEqual(archive.read('assets/'+name),original)
        url=f'/learning/sessions/{self.session.id}/assets/{name}'
        response = self.client.get(url)
        self.assertEqual(response.status_code,200)
        response.close()
        self.login(self.a)
        self.assertEqual(self.client.get(url).status_code,404)

    def test_student_question_review_and_teacher_notes(self):
        settings=db.session.get(AnalyticsSessionSettings,self.session.id)
        settings.teacher_notes='SECRETNOTE'
        settings.student_feedback='Good effort'
        db.session.commit()
        self.publish()
        self.login(self.a)
        qid=AnalyticsRoundProblem.query.first().id
        response=self.client.get(f'/player/learning/sessions/{self.session.id}/questions/{qid}')
        self.assertEqual(response.status_code,200)
        self.assertIn('5 N',response.get_data(as_text=True))
        self.assertNotIn('SECRETNOTE',response.get_data(as_text=True))
        html=self.client.get(f'/player/learning/sessions/{self.session.id}').get_data(as_text=True)
        self.assertIn('Good effort',html)
        self.assertNotIn('SECRETNOTE',html)

    def test_open_session_and_incomplete_evidence(self):
        self.session.group=None
        pp=AnalyticsPlayerProblem.query.filter_by(player_id=self.a.id,mode_context='boss_rush_attack').one()
        pp.attempt_count=9
        db.session.flush()
        r=build_session_report(self.session)
        self.assertEqual(r['students'][0]['cells'][0]['state'],'incomplete')
        self.assertEqual(r['metrics']['incomplete'],1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
