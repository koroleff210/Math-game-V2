# app/modes/classic/forms.py
#
# WTForms for Classic Mode admin UI.
# Kept separate from app/routes/forms.py to preserve module isolation.

from flask_wtf import FlaskForm
from wtforms import BooleanField, FloatField, IntegerField, SelectField, StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, NumberRange, Length, Optional, ValidationError


class ClassicConfigFieldsForm(FlaskForm):
    """Shared Classic round-config fields and cross-field validation."""

    # Core settings
    mine_reward = IntegerField(
        'Mine Reward (gold)',
        default=20,
        validators=[NumberRange(min=0, message='Must be 0 or more.')],
    )
    treasure_search_reward = IntegerField(
        'Min Treasure Search Reward (gold)',
        default=5,
        validators=[NumberRange(min=0)],
    )
    attempts_per_problem = IntegerField(
        'Attempts per Problem (-1 = unlimited)',
        default=1,
        validators=[NumberRange(min=-1, message='Use -1 for unlimited or 1+.')],
    )
    wrong_answer_penalty = IntegerField(
        'Wrong Answer Penalty (gold)',
        default=0,
        validators=[NumberRange(min=0)],
    )

    # Timer bonus
    bonus_timer_duration = IntegerField(
        'Timer Bonus Duration (seconds, 0 = disabled)',
        default=120,
        validators=[NumberRange(min=0)],
    )
    bonus_timer_gold = IntegerField(
        'Timer Bonus Gold',
        default=5,
        validators=[NumberRange(min=0)],
    )

    # First-solver bonus
    first_solver_count = IntegerField(
        'First Solver Count (how many solvers get bonus)',
        default=3,
        validators=[NumberRange(min=0)],
    )
    first_solver_multiplier = IntegerField(
        'First Solver Multiplier (gold per rank slot)',
        default=2,
        validators=[NumberRange(min=0)],
    )

    # Random rewards & gems
    treasure_search_max_reward = IntegerField(
        'Max Treasure Search Reward (gold)',
        default=5,
        validators=[NumberRange(min=0, message='Must be 0 or more.')],
    )
    gem_milestone_count = IntegerField(
        'Gem Milestone (problems solved per +1 gem, 0 = disabled)',
        default=5,
        validators=[NumberRange(min=0, message='Must be 0 or more.')],
    )
    gem_streak_count = IntegerField(
        'Gem Streak (consecutive correct answers per +1 gem, 0 = disabled)',
        default=3,
        validators=[NumberRange(min=0, message='Must be 0 or more.')],
    )
    gem_treasure_chance = FloatField(
        'Gem Chest Fill Chance (0-1)',
        default=0.5,
        validators=[NumberRange(min=0.0, max=1.0, message='Must be between 0 and 1.')],
    )

    # Steal system
    steal_percent = FloatField(
        'Steal Percent (0-1)',
        default=0.10,
        validators=[NumberRange(min=0.0, max=1.0, message='Must be between 0 and 1.')],
    )
    steal_min_cap = IntegerField(
        'Steal Min Cap (gold)',
        default=10,
        validators=[NumberRange(min=0, message='Must be 0 or more.')],
    )
    steal_max_cap = IntegerField(
        'Steal Max Cap (gold, -1 = no cap)',
        default=50,
        validators=[NumberRange(min=-1, message='Use -1 for no cap or 0+.')],
    )
    steal_fallback_gold = IntegerField(
        'Stranger Steal Gold',
        default=5,
        validators=[NumberRange(min=0, message='Must be 0 or more.')],
    )
    steal_chest_count = IntegerField(
        'Mini-game Chest Count (0 = disabled)',
        default=6,
        validators=[NumberRange(min=0, message='Must be 0 or more.')],
    )
    steal_winning_chest_count = IntegerField(
        'Mini-game Winning Chests',
        default=4,
        validators=[NumberRange(min=1, message='Must be at least 1.')],
    )
    active_shield_duration = IntegerField(
        'Shield Token Duration (seconds)',
        default=60,
        validators=[NumberRange(min=0, message='Must be 0 or more.')],
    )
    reactive_shield_duration = IntegerField(
        'Reactive Protection Duration (seconds)',
        default=20,
        validators=[NumberRange(min=0, message='Must be 0 or more.')],
    )
    treasure_steal_token_chance = FloatField(
        'Steal Token Chest Fill Chance (0-1)',
        default=0.6,
        validators=[NumberRange(min=0.0, max=1.0, message='Must be between 0 and 1.')],
    )
    treasure_active_shield_chance = FloatField(
        'Shield Token Chest Fill Chance (0-1)',
        default=0.6,
        validators=[NumberRange(min=0.0, max=1.0, message='Must be between 0 and 1.')],
    )
    treasure_second_chance_chance = FloatField(
        'Second Chance Chest Fill Chance (0-1)',
        default=0.5,
        validators=[NumberRange(min=0.0, max=1.0, message='Must be between 0 and 1.')],
    )

    def validate_treasure_search_max_reward(self, field):
        """Cross-field: max must be >= min (treasure_search_reward)."""
        ts_min = self.treasure_search_reward.data
        if field.data is not None and ts_min is not None and field.data < ts_min:
            raise ValidationError(
                f'Max ({field.data}) must be >= Min Treasure Search Reward ({ts_min}).'
            )

    def validate_steal_winning_chest_count(self, field):
        """Cross-field: winning chests cannot exceed total mini-game chests."""
        chest_count = self.steal_chest_count.data
        if chest_count is not None and field.data is not None and chest_count > 0:
            if field.data > chest_count:
                raise ValidationError(
                    f'Winning chests ({field.data}) must be <= '
                    f'total mini-game chests ({chest_count}).'
                )


class ClassicSessionForm(ClassicConfigFieldsForm):
    """Admin form: create a new Classic Mode session with round configuration."""

    problem_set_id = SelectField(
        'Problem Set',
        coerce=int,
        validators=[DataRequired()],
    )

    # G1: optional class restriction and session label
    group_id = SelectField(
        'Restrict to Class',
        coerce=int,
        choices=[],
        validators=[Optional()],
    )
    label = StringField('Session Label (optional)', validators=[Optional()])

    submit = SubmitField('Create Session')


class StoreItemForm(FlaskForm):
    """Admin form: add or edit a store item for a Classic session."""

    name = StringField(
        'Item Name',
        validators=[DataRequired(), Length(max=80)],
    )
    description = TextAreaField(
        'Description (optional)',
        validators=[Length(max=255)],
    )
    cost = IntegerField(
        'Cost',
        default=10,
        validators=[NumberRange(min=1, message='Must be at least 1.')],
    )
    currency = SelectField(
        'Currency',
        choices=[
            ('gold', 'Gold 💰'),
            ('gems', 'Gems 💎'),
        ],
        default='gold',
        validators=[DataRequired()],
    )
    bonus_type = SelectField(
        'Bonus Type',
        choices=[
            ('x2_mine', '×2 Mine Reward (one-time use)'),
            ('shield', 'Second Chance — try again with no penalty (one-time use)'),
            ('steal_token', 'Steal Token — immediately credits 1 steal token'),
            ('steal_shield', 'Shield Token — manual anti-steal protection token'),
        ],
        validators=[DataRequired()],
    )
    session_stock = IntegerField(
        'Session Stock (-1 = unlimited)',
        default=-1,
        validators=[NumberRange(min=-1, message='Use -1 for unlimited or 1+.')],
    )
    per_player_limit = IntegerField(
        'Per-Player Limit (-1 = unlimited)',
        default=-1,
        validators=[NumberRange(min=-1, message='Use -1 for unlimited or 1+.')],
    )

    submit = SubmitField('Save Item')


class NextRoundForm(ClassicConfigFieldsForm):
    """Admin form: start the next round within an existing session.

    All ClassicRoundConfig fields are editable, pre-filled from the previous
    round's config so admin can keep defaults or tweak individual values.

    carry_over_gold / carry_over_gems: if checked (True, the default), player
    gold/gems are preserved. Unchecked = reset to 0.
    """

    carry_over_gold = BooleanField('Carry over gold', default=True)
    carry_over_gems = BooleanField('Carry over gems', default=True)
    problem_set_id = SelectField(
        'Problem Set for next round',
        coerce=int,
        choices=[],
        validators=[],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.first_solver_count.label.text = 'First Solver Count'
        self.first_solver_multiplier.label.text = 'First Solver Multiplier'
        self.gem_milestone_count.label.text = 'Gem Milestone (0 = disabled)'
        self.gem_streak_count.label.text = 'Gem Streak (0 = disabled)'

    submit = SubmitField('Start Next Round')
