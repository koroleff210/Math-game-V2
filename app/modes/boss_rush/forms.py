# app/modes/boss_rush/forms.py
#
# WTForms for Boss Rush admin setup.

from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, NumberRange, Optional

from app.modes.boss_rush.engine import DEFAULT_BOSS_RUSH_SETTINGS, boss_type_choices


class BossRushSessionForm(FlaskForm):
    attack_problem_set_id = SelectField(
        'Attack Problem Set',
        coerce=int,
        validators=[DataRequired()],
    )
    recovery_problem_set_id = SelectField(
        'Recovery Problem Set',
        coerce=int,
        validators=[DataRequired()],
    )
    group_id = SelectField(
        'Restrict to Class',
        coerce=int,
        choices=[],
        validators=[Optional()],
    )
    label = StringField('Session Label (optional)', validators=[Optional()])

    boss_type = SelectField(
        'Boss Type',
        choices=boss_type_choices(),
        validators=[DataRequired()],
        default='fire_giant',
    )
    boss_max_hp = IntegerField(
        'Boss HP',
        default=DEFAULT_BOSS_RUSH_SETTINGS['boss_max_hp'],
        validators=[NumberRange(min=1, message='Boss HP must be at least 1.')],
    )
    player_max_hp = IntegerField(
        'Player HP',
        default=DEFAULT_BOSS_RUSH_SETTINGS['player_max_hp'],
        validators=[NumberRange(min=1, message='Player HP must be at least 1.')],
    )

    first_place_diamonds = IntegerField(
        '1st Place Diamonds',
        default=DEFAULT_BOSS_RUSH_SETTINGS['first_place_diamonds'],
        validators=[NumberRange(min=0)],
    )
    second_place_diamonds = IntegerField(
        '2nd Place Diamonds',
        default=DEFAULT_BOSS_RUSH_SETTINGS['second_place_diamonds'],
        validators=[NumberRange(min=0)],
    )
    third_place_diamonds = IntegerField(
        '3rd Place Diamonds',
        default=DEFAULT_BOSS_RUSH_SETTINGS['third_place_diamonds'],
        validators=[NumberRange(min=0)],
    )
    other_participant_diamonds = IntegerField(
        'Other Damage Participant Diamonds',
        default=DEFAULT_BOSS_RUSH_SETTINGS['other_participant_diamonds'],
        validators=[NumberRange(min=0)],
    )
    highest_combo_diamonds = IntegerField(
        'Highest Combo Diamonds',
        default=DEFAULT_BOSS_RUSH_SETTINGS['highest_combo_diamonds'],
        validators=[NumberRange(min=0)],
    )
    combo_bonus_threshold = IntegerField(
        'Combo Bonus Threshold (-1 = disabled)',
        default=DEFAULT_BOSS_RUSH_SETTINGS['combo_bonus_threshold'],
        validators=[NumberRange(min=-1)],
    )
    combo_bonus_damage = IntegerField(
        'Combo Bonus Damage',
        default=DEFAULT_BOSS_RUSH_SETTINGS['combo_bonus_damage'],
        validators=[NumberRange(min=0)],
    )
    ability_enabled = BooleanField(
        'Enable Boss Abilities',
        default=DEFAULT_BOSS_RUSH_SETTINGS['ability_enabled'],
    )
    ability_interval_seconds = IntegerField(
        'Ability Interval Seconds',
        default=DEFAULT_BOSS_RUSH_SETTINGS['ability_interval_seconds'],
        validators=[NumberRange(min=0)],
    )
    fire_burn_damage = IntegerField(
        'Fire Burn Damage',
        default=DEFAULT_BOSS_RUSH_SETTINGS['fire_burn_damage'],
        validators=[NumberRange(min=0)],
    )
    fire_shield_max_stacks = IntegerField(
        'Fire Shield Max Stacks',
        default=DEFAULT_BOSS_RUSH_SETTINGS['fire_shield_max_stacks'],
        validators=[NumberRange(min=0)],
    )
    swamp_regen_amount = IntegerField(
        'Swamp Regen Amount',
        default=DEFAULT_BOSS_RUSH_SETTINGS['swamp_regen_amount'],
        validators=[NumberRange(min=0)],
    )
    stone_guard_combo_required = IntegerField(
        'Stone Guard Combo Required',
        default=DEFAULT_BOSS_RUSH_SETTINGS['stone_guard_combo_required'],
        validators=[NumberRange(min=1)],
    )
    time_drain_damage = IntegerField(
        'Time Drain Damage',
        default=DEFAULT_BOSS_RUSH_SETTINGS['time_drain_damage'],
        validators=[NumberRange(min=0)],
    )

    submit = SubmitField('Create Boss Rush')
