# app/routes/forms.py
#
# WTForms form classes for admin CRUD.
# All forms extend FlaskForm, which automatically adds CSRF protection.

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, IntegerField, SubmitField, BooleanField, PasswordField
from wtforms.validators import DataRequired, InputRequired, Optional, Length, NumberRange
from app.models.gear import GEAR_SLOT_TYPES
from app.models.problems import (
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    PROBLEM_ANSWER_TYPE_TEXT_INPUT,
)


class SubjectForm(FlaskForm):
    name = StringField(
        'Subject Name',
        validators=[DataRequired(), Length(max=64)],
    )
    description = StringField(
        'Description (optional)',
        validators=[Optional(), Length(max=256)],
    )
    submit = SubmitField('Save Subject')


class TopicForm(FlaskForm):
    name = StringField(
        'Topic Name',
        validators=[DataRequired(), Length(max=128)],
    )
    subject = StringField(
        'Subject string (legacy, optional)',
        validators=[Optional(), Length(max=64)],
    )
    # subject_id choices are populated dynamically in the route.
    subject_id = SelectField(
        'Subject',
        coerce=int,
        validators=[Optional()],
    )
    description = TextAreaField(
        'Description (optional)',
        validators=[Optional()],
    )
    submit = SubmitField('Save Topic')


class ProblemForm(FlaskForm):
    title = StringField(
        'Title',
        validators=[DataRequired(), Length(max=256)],
    )
    # topic_id choices are populated dynamically in the route, not here.
    topic_id = SelectField(
        'Topic',
        coerce=int,
        validators=[DataRequired()],
    )
    prompt_text = TextAreaField(
        'Question (plain text or LaTeX)',
        validators=[DataRequired()],
    )
    answer_text = StringField(
        'Answer',
        validators=[Optional(), Length(max=512)],
    )
    answer_type = SelectField(
        'Answer Type',
        choices=[
            (PROBLEM_ANSWER_TYPE_TEXT_INPUT, 'Text input'),
            (PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE, 'Multiple choice'),
        ],
        validators=[DataRequired()],
        default=PROBLEM_ANSWER_TYPE_TEXT_INPUT,
    )
    difficulty = SelectField(
        'Difficulty',
        choices=[(1, '1 — Easy'), (2, '2'), (3, '3 — Medium'), (4, '4'), (5, '5 — Hard')],
        coerce=int,
        default=1,
    )
    image_path = StringField(
        'Image path (optional)',
        validators=[Optional(), Length(max=512)],
    )
    submit = SubmitField('Save Problem')


class ProblemSetForm(FlaskForm):
    name = StringField(
        'Set Name',
        validators=[DataRequired(), Length(max=128)],
    )
    description = TextAreaField(
        'Description (optional)',
        validators=[Optional()],
    )
    usable_in_classic = BooleanField('Classic', default=True)
    usable_in_boss_rush = BooleanField('Boss Rush attack', default=False)
    usable_as_recovery = BooleanField('Boss Rush recovery', default=False)
    usable_in_team = BooleanField('Team later', default=False)
    submit = SubmitField('Save Problem Set')


class PlayerCreateForm(FlaskForm):
    username  = StringField('Username', validators=[DataRequired(), Length(max=64)])
    password  = PasswordField('Password (optional for students)', validators=[Optional(), Length(min=8, max=256)])
    shared_email = StringField('Student email (shared login)', validators=[Optional(), Length(max=254)])
    yeargroup = StringField('Year Group (optional)', validators=[Optional(), Length(max=32)])
    is_admin  = BooleanField('Admin account')
    submit    = SubmitField('Create Player')

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        if self.is_admin.data and not self.password.data:
            self.password.errors.append('Set a password for an admin account.')
            valid = False
        from app.services.shared_identity import enabled
        if enabled() and not self.is_admin.data and not (self.shared_email.data or '').strip():
            self.shared_email.errors.append('Enter the student email to use the shared login on both sites.')
            valid = False
        return valid


class PlayerEditForm(FlaskForm):
    shared_email = StringField('Student email (shared login)', validators=[Optional(), Length(max=254)])
    username     = StringField('Username', validators=[DataRequired(), Length(max=64)])
    new_password = PasswordField('New Password (leave blank to keep current)',
                                 validators=[Optional(), Length(min=8, max=256)])
    yeargroup    = StringField('Year Group (optional)', validators=[Optional(), Length(max=32)])
    is_admin     = BooleanField('Admin account')
    submit       = SubmitField('Save Changes')


class PlayerGroupForm(FlaskForm):
    name        = StringField('Class Name', validators=[DataRequired(), Length(max=64)])
    description = TextAreaField('Description', validators=[Optional()])
    submit      = SubmitField('Save')


class DiamondAwardForm(FlaskForm):
    """Form for awarding Diamonds to a player (admin-only).

    player_id choices are populated dynamically in the route.
    """
    player_id = SelectField(
        'Player',
        coerce=int,
        validators=[DataRequired()],
    )
    amount = IntegerField(
        'Amount',
        validators=[DataRequired(), NumberRange(min=1, message='Amount must be at least 1.')],
    )
    reason = StringField(
        'Reason',
        validators=[DataRequired(), Length(max=64)],
    )
    submit = SubmitField('Award Diamonds')


class GearItemForm(FlaskForm):
    item_id = StringField(
        'Item ID',
        validators=[DataRequired(), Length(max=64)],
    )
    name = StringField(
        'Display Name',
        validators=[DataRequired(), Length(max=80)],
    )
    slot_type = SelectField(
        'Slot Type',
        choices=[(slot, slot.replace('_', ' ').title()) for slot in GEAR_SLOT_TYPES],
        validators=[DataRequired()],
    )
    description = TextAreaField(
        'Description',
        validators=[DataRequired(), Length(max=255)],
    )
    image_key = SelectField(
        'Image',
        choices=[],
        validators=[Optional()],
    )
    avatar_asset_key = StringField(
        'Avatar Asset Key (optional)',
        validators=[Optional(), Length(max=16)],
    )
    diamond_cost = IntegerField(
        'Diamond Cost',
        validators=[InputRequired(), NumberRange(min=0, message='Diamond cost must be 0 or higher.')],
    )
    mine_gold_delta = IntegerField(
        'Mine Gold Delta',
        validators=[InputRequired()],
        default=0,
    )
    steal_gold_delta = IntegerField(
        'Steal Gold Delta',
        validators=[InputRequired()],
        default=0,
    )
    shield_duration_delta = IntegerField(
        'Shield Duration Delta (seconds)',
        validators=[InputRequired()],
        default=0,
    )
    is_active = BooleanField('Active', default=True)
    is_blacksmith_visible = BooleanField('Visible in Blacksmith', default=True)
    submit = SubmitField('Save Gear Item')
