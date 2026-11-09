"""Focused UI data/asset regressions. Browser timing is verified separately."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageChops
from bs4 import BeautifulSoup
from flask import g, template_rendered
from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.gear import GearItemDefinition, PlayerGearOwnership, PlayerGearLoadout
from app.models.progression import PlayerProgression, PlayerUpgrade


class Config:
    TESTING=True
    SQLALCHEMY_DATABASE_URI='sqlite:///:memory:'
    SECRET_KEY='ui-loading-isolated'
    SQLALCHEMY_TRACK_MODIFICATIONS=False
    SOCKETIO_ASYNC_MODE='threading'
    WTF_CSRF_ENABLED=False


class PlayerUITests(unittest.TestCase):
    def setUp(self):
        self.app=create_app(Config)
        self.context=self.app.app_context()
        self.context.push()
        db.create_all()
        self.player=Player(username='ui-player',password_hash='unused',character_locked_at=datetime.now(timezone.utc))
        db.session.add(self.player)
        db.session.flush()
        db.session.add(PlayerProgression(player_id=self.player.id,diamonds_balance=100))
        self.item=GearItemDefinition(id='ui-owned',name='Owned shovel',slot_type='main_hand',avatar_asset_key='001',diamond_cost=3,mine_gold_delta=3)
        self.other=Player(username='other-ui',password_hash='unused')
        self.other_item=GearItemDefinition(id='other-owned',name='Other player private gear',slot_type='off_hand')
        db.session.add_all([self.item,self.other,self.other_item])
        db.session.flush()
        db.session.add_all([PlayerGearOwnership(player_id=self.player.id,item_id=self.item.id),
                            PlayerGearOwnership(player_id=self.other.id,item_id=self.other_item.id),
                            PlayerGearLoadout(player_id=self.player.id,main_hand_item_id=self.item.id),
                            PlayerUpgrade(player_id=self.player.id,upgrade_type='mine_bonus',level=2)])
        db.session.commit()
        self.client=self.app.test_client()
        with self.client.session_transaction() as session:
            session['_user_id']=str(self.player.id)
            session['_fresh']=True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def test_blacksmith_shows_single_owned_list_with_equipped_highlight(self):
        captured=[]
        def capture(sender,template,context,**kwargs):captured.append(context)
        with template_rendered.connected_to(capture,self.app):
            response=self.client.get('/player/blacksmith')
        self.assertEqual(response.status_code,200)
        panel=captured[-1]['inventory_view']
        self.assertEqual([i['id'] for i in panel['inventory_items']],['ui-owned'])
        self.assertEqual([i['id'] for i in panel['comparison_items']],['ui-owned'])
        main=next(s for s in panel['slot_rows'] if s['slot_key']=='main_hand')
        self.assertEqual(main['item']['mine_gold_delta'],3)
        self.assertTrue(panel['inventory_items'][0]['is_equipped'])
        mine=next(u for u in captured[-1]['upgrades'] if u['upgrade_type']=='mine_bonus')
        self.assertEqual(mine['current_level'],2)
        html=response.get_data(as_text=True)
        inventory = BeautifulSoup(html, 'html.parser').select_one('[data-smith-inventory]')
        self.assertIn('Owned gear', inventory.get_text())
        self.assertEqual(len(inventory.select('[data-owned-gear="ui-owned"]')), 1)
        self.assertIsNotNone(inventory.select_one('[data-owned-gear="ui-owned"].is-equipped'))
        self.assertFalse(inventory.select('[data-current-upgrade]'))
        self.assertNotIn('Equipped now', inventory.get_text())
        self.assertNotIn('Other player private gear', inventory.get_text())
        self.assertIn('data-ui-fullscreen',html)

    def test_purchase_refreshes_current_level_panel(self):
        response=self.client.post('/player/blacksmith/buy',data={'upgrade_type':'mine_bonus','return_tab':'upgrades'},follow_redirects=True)
        self.assertEqual(response.status_code,200)
        self.assertEqual(PlayerUpgrade.query.filter_by(player_id=self.player.id,upgrade_type='mine_bonus').one().level,3)
        card = BeautifulSoup(response.get_data(as_text=True), 'html.parser').select_one('[data-upgrade-type="mine_bonus"]')
        self.assertIn('3 of', card.select_one('.upgrade-level-track')['aria-label'])

    def test_gender_shell_transition_and_preload_metadata(self):
        self.player.character_locked_at=None
        self.player.avatar_gender_selected=False
        db.session.commit()
        first=self.client.get('/player/dashboard').get_data(as_text=True)
        self.assertIn('data-ui-shell-kind="gender"',first)
        response=self.client.post('/player/avatar/body',data={'variant':'f'},headers={'X-Requested-With':'XMLHttpRequest'})
        html=response.get_data(as_text=True)
        self.assertEqual(response.status_code,200)
        self.assertIn('data-ui-shell-kind="character"',html)
        self.assertIn('data-ui-preloads',html)
        self.assertIn('/static/optimized/',html)
        self.assertEqual(self.player.avatar_body_variant,'f')

    def test_readiness_is_only_on_player_pages(self):
        html=self.client.get('/player/dashboard').get_data(as_text=True)
        self.assertIn('id="ui-page-loader"',html)
        self.assertIn('player_ui.js',html)
        self.assertIn('fetchpriority="high"',html)
        login=self.client.get('/login').get_data(as_text=True)
        self.assertNotIn('id="ui-page-loader"',login)

    def test_top_level_browser_get_uses_persistent_container_only_once(self):
        with self.client.session_transaction() as session:
            session['_flashes'] = [('info', 'Keep this message for the actual page')]
        top = self.client.get('/player/blacksmith?tab=gear', headers={'Sec-Fetch-Dest': 'document'})
        self.assertEqual(top.status_code, 200)
        self.assertIn('Sec-Fetch-Dest', top.headers['Vary'])
        self.assertIn('no-store', top.headers['Cache-Control'])
        html = BeautifulSoup(top.get_data(as_text=True), 'html.parser')
        self.assertEqual(html.select_one('#player-page-frame')['src'], '/player/blacksmith?tab=gear')
        self.assertEqual(len(html.select('[data-ui-fullscreen]')), 1)
        with self.client.session_transaction() as session:
            self.assertEqual(session['_flashes'][0][1], 'Keep this message for the actual page')
        child = self.client.get('/player/blacksmith?tab=gear', headers={'Sec-Fetch-Dest': 'iframe'})
        child_html = BeautifulSoup(child.get_data(as_text=True), 'html.parser')
        self.assertIsNone(child_html.select_one('#player-page-frame'))
        self.assertIsNotNone(child_html.select_one('.blacksmith-page'))
        self.assertIn('Keep this message for the actual page', child.get_data(as_text=True))

    def test_container_keeps_authentication_and_partial_routes(self):
        partial = self.client.get('/player/gear/shell', headers={'Sec-Fetch-Dest': 'empty', 'X-Requested-With': 'XMLHttpRequest'})
        self.assertNotIn('player-page-frame', partial.get_data(as_text=True))
        for path in ['/player/dashboard', '/player/blacksmith', '/player/progress', '/player/history']:
            html = BeautifulSoup(self.client.get(path, headers={'Sec-Fetch-Dest': 'iframe'}).get_data(as_text=True), 'html.parser')
            self.assertEqual(len(html.select('[data-ui-fullscreen]')), 1, path)
        g.pop('_login_user', None)
        anonymous = self.app.test_client().get('/player/dashboard', headers={'Sec-Fetch-Dest': 'document'})
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn('/login', anonymous.headers['Location'])

    def test_display_asset_cache_and_fallback(self):
        manifest=json.loads((Path(self.app.static_folder)/'optimized'/'manifest.json').read_text())
        entry=manifest['classic_ui/player_ui/background_001.png']
        response=self.client.get('/static/'+entry['path'])
        self.assertEqual(response.status_code,200)
        self.assertIn('immutable',response.headers['Cache-Control'])
        self.assertEqual(sha256(response.data).hexdigest(),Path(entry['path']).stem)
        response.close()
        transform=self.app.jinja_env.filters['ui_image']
        self.assertEqual(transform('/media/123'),'/media/123')
        self.assertEqual(transform('/static/not-in-manifest.png'),'/static/not-in-manifest.png')

    def test_background_savings_and_avatar_alpha_alignment(self):
        root=Path(self.app.static_folder)
        manifest=json.loads((root/'optimized'/'manifest.json').read_text())
        for key in ['classic_ui/player_ui/background_001.png','classic_ui/player_ui/blacksmith_bg.png','classic_ui/player_ui/panel_texture.png']:
            entry=manifest[key]
            self.assertLess(entry['display_bytes'],entry['original_bytes']*.15)
            self.assertEqual(sha256((root/key).read_bytes()).hexdigest(),entry['source_sha256'])
        for key in ['gear/face/face_001.png','avatars/bodies/m/body_upper.png','avatars/bodies/f/body_lower.png']:
            with Image.open(root/key) as original,Image.open(root/manifest[key]['path']) as display:
                self.assertEqual(original.size,display.size)
                self.assertIsNone(ImageChops.difference(original.convert('RGBA').getchannel('A'),display.convert('RGBA').getchannel('A')).getbbox())


if __name__=='__main__':
    unittest.main(verbosity=2)
