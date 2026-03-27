# app/models/__init__.py
# Import all models here so Flask-Migrate can detect them when running migrations.
# Add a new import line each time a new model file is created.

from app.models.player   import Player                            # noqa: F401
from app.models.subjects import Subject                           # noqa: F401
from app.models.problems import Topic, Problem, ProblemSet, ProblemBlock, ProblemAcceptedAnswer, ProblemChoiceOption  # noqa: F401
from app.models.game     import GameSession, GameRound, RoundPlayer, PlayerAnswer  # noqa: F401
from app.models.classic  import ClassicRoundConfig, PlayerWallet, PlayerClassicState, PlayerProblemState, ProblemSolverCount, StoreItem, PlayerInventory, StealEvent  # noqa: F401
from app.models.groups   import PlayerGroup, player_group_members  # noqa: F401
from app.models.history      import RoundHistory, RoundPlayerResult   # noqa: F401
from app.models.progression  import PlayerProgression, DiamondTransaction, PlayerUpgrade, SessionParticipantSnapshot  # noqa: F401
from app.models.gear         import GearItemDefinition, PlayerGearOwnership, PlayerGearLoadout  # noqa: F401
