# seed.py
#
# Creates initial users in the database.
# Safe to run multiple times — only creates users that do not already exist.
#
# Usage:
#   python seed.py

from app import create_app
from app.extensions import db
from app.models.gear import PlayerGearLoadout, PlayerGearOwnership
from app.models.player import Player
from app.services.gear import ensure_sample_gear_items


# ── Users to seed ─────────────────────────────────────────────────────────────
SEED_USERS = [
    {'username': 'admin',   'password': 'admin123',  'is_admin': True},
    {'username': 'player1', 'password': 'player123', 'is_admin': False},
    {'username': 'player2', 'password': 'player123', 'is_admin': False},
]


def seed():
    app = create_app()

    with app.app_context():
        created = 0

        for user_data in SEED_USERS:
            # Skip if this username already exists in the database.
            existing = Player.query.filter_by(username=user_data['username']).first()
            if existing:
                print(f'  [skip]    {user_data["username"]} already exists')
                continue

            player = Player(
                username=user_data['username'],
                is_admin=user_data['is_admin']
            )
            player.set_password(user_data['password'])
            db.session.add(player)
            created += 1
            role = 'admin' if user_data['is_admin'] else 'player'
            print(f'  [created] {user_data["username"]} ({role})')

        created_items = ensure_sample_gear_items()

        player1 = Player.query.filter_by(username='player1').first()
        if player1 is not None:
            owned_ids = {
                row.item_id
                for row in PlayerGearOwnership.query.filter_by(player_id=player1.id).all()
            }
            for item_id in [
                'bronze_pickaxe',
                'oak_buckler',
                'lucky_coin',
                'test_helmet_001',
                'test_chest_001',
                'test_boots_001',
                'test_main_hand_001',
                'test_off_hand_001',
            ]:
                if item_id not in owned_ids:
                    db.session.add(
                        PlayerGearOwnership(player_id=player1.id, item_id=item_id)
                    )

            loadout = PlayerGearLoadout.query.filter_by(player_id=player1.id).first()
            if loadout is None:
                loadout = PlayerGearLoadout(player_id=player1.id)
                db.session.add(loadout)
                db.session.flush()
            loadout.main_hand_item_id = 'bronze_pickaxe'
            loadout.off_hand_item_id = 'oak_buckler'
            loadout.pocket1_item_id = 'lucky_coin'

        db.session.commit()
        print(f'\nDone. {created} user(s) created.')
        print(f'Gear catalog ready: {len(created_items)} item(s) created this run.')
        print('Sample gear ownership/loadout applied to player1.')


if __name__ == '__main__':
    seed()
