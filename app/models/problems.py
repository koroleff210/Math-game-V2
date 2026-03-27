# app/models/problems.py
#
# Three models that make up the problem bank:
#   Topic       — a category (e.g. "Algebra", "Fractions")
#   Problem     — a single question with an answer
#   ProblemSet  — a named collection of Problems used in a game round

from datetime import datetime, timezone
from app.extensions import db


PROBLEM_ANSWER_TYPE_TEXT_INPUT = 'text_input'
PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE = 'multiple_choice'

PROBLEM_BLOCK_TYPE_RICH_TEXT = 'rich_text'
PROBLEM_BLOCK_TYPE_IMAGE = 'image'
PROBLEM_BLOCK_TYPE_GRAPH = 'graph'


# ── Association table ─────────────────────────────────────────────────────────
# Many-to-many: one ProblemSet can hold many Problems, and the same Problem can
# appear in multiple ProblemSets.

problem_set_problems = db.Table(
    'problem_set_problems',
    db.Column('problem_set_id', db.Integer, db.ForeignKey('problem_set.id'), primary_key=True),
    db.Column('problem_id',     db.Integer, db.ForeignKey('problem.id'),     primary_key=True),
)


# ── Topic ─────────────────────────────────────────────────────────────────────

class Topic(db.Model):
    __tablename__ = 'topic'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(128), unique=True, nullable=False)
    # subject: legacy string field — kept for transition; do NOT remove.
    subject     = db.Column(db.String(64), nullable=True)
    # subject_id: FK to Subject model — nullable during transition.
    subject_id  = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True)
    description = db.Column(db.Text, nullable=True)

    # All problems belonging to this topic.
    problems = db.relationship('Problem', backref='topic', lazy='dynamic')

    def __repr__(self):
        return f'<Topic {self.name!r}>'


# ── Problem ───────────────────────────────────────────────────────────────────

class Problem(db.Model):
    __tablename__ = 'problem'

    id         = db.Column(db.Integer, primary_key=True)
    topic_id   = db.Column(db.Integer, db.ForeignKey('topic.id'), nullable=False)

    # title: short label shown in admin lists (e.g. "Fractions Q1")
    title      = db.Column(db.String(256), nullable=False)

    # prompt_text: the question itself.
    # Plain text is fine; LaTeX in $...$ or $$...$$ syntax is also supported —
    # MathJax will render it in the browser without any server-side changes.
    prompt_text = db.Column(db.Text, nullable=False)

    # answer_text: the expected answer. Stored as plain text for now.
    # Case-insensitive comparison is done at check time, not here.
    answer_text = db.Column(db.String(512), nullable=False)

    # answer_type: answer-mode scaffold for the evolving problem system.
    # V1 Slice 1 only uses text_input, but the field exists now so new
    # content can migrate incrementally without replacing Problem as the root.
    answer_type = db.Column(
        db.String(32),
        nullable=False,
        default=PROBLEM_ANSWER_TYPE_TEXT_INPUT,
    )

    # difficulty: integer 1 (easy) to 5 (hard) — used later for scoring rules.
    difficulty  = db.Column(db.Integer, default=1, nullable=False)

    # image_path: relative path inside static/ (e.g. "images/q42.png").
    # Null when no image is needed.
    image_path  = db.Column(db.String(512), nullable=True)

    # graph_config_json: JSON string holding a Plotly figure config.
    # Null when no graph is needed.  Plotly rendering is wired in Phase 4+.
    graph_config_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    blocks = db.relationship(
        'ProblemBlock',
        backref='problem',
        order_by='ProblemBlock.position',
        cascade='all, delete-orphan',
        lazy='select',
    )
    accepted_answers = db.relationship(
        'ProblemAcceptedAnswer',
        backref='problem',
        order_by='ProblemAcceptedAnswer.position',
        cascade='all, delete-orphan',
        lazy='select',
    )
    choice_options = db.relationship(
        'ProblemChoiceOption',
        backref='problem',
        order_by='ProblemChoiceOption.position',
        cascade='all, delete-orphan',
        lazy='select',
    )

    def __repr__(self):
        return f'<Problem {self.id}: {self.title!r}>'


# ── ProblemSet ────────────────────────────────────────────────────────────────

class ProblemSet(db.Model):
    __tablename__ = 'problem_set'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at  = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # problems: the Problems in this set (order not guaranteed — ordering is
    # handled by the game engine at round time, not at the set level).
    problems = db.relationship(
        'Problem',
        secondary=problem_set_problems,
        backref=db.backref('problem_sets', lazy='dynamic'),
        lazy='dynamic',
    )

    def __repr__(self):
        return f'<ProblemSet {self.id}: {self.name!r}>'


class ProblemBlock(db.Model):
    __tablename__ = 'problem_block'

    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=1)
    block_type = db.Column(db.String(32), nullable=False)

    # V1 Slice 1 block payload fields:
    # - rich_text uses text_content
    # - image uses image_path + image_width_pct
    # - graph uses graph_config_json
    # Future block types can add fields later without replacing the body model.
    text_content = db.Column(db.Text, nullable=True)
    image_path = db.Column(db.String(512), nullable=True)
    image_width_pct = db.Column(db.Integer, nullable=True)
    graph_config_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return f'<ProblemBlock {self.id} problem={self.problem_id} type={self.block_type!r}>'


class ProblemAcceptedAnswer(db.Model):
    __tablename__ = 'problem_accepted_answer'

    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=1)
    answer_text = db.Column(db.String(512), nullable=False)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return f'<ProblemAcceptedAnswer {self.id} problem={self.problem_id}>'


class ProblemChoiceOption(db.Model):
    __tablename__ = 'problem_choice_option'

    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=1)
    option_text = db.Column(db.String(512), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return f'<ProblemChoiceOption {self.id} problem={self.problem_id}>'
