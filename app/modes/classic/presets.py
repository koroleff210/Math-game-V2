"""Starting points for the Classic session form. Admins can edit every value."""

_BASE = dict(
    attempts_per_problem=1, wrong_answer_penalty=0, combo_start=3,
    treasure_pity_increment=.12, treasure_pity_cap=.85,
    treasure_search_reward=0, treasure_search_max_reward=0,
    treasure_double_mine_chance=0, gem_treasure_chance=0,
    treasure_steal_token_chance=0, treasure_active_shield_chance=0,
    treasure_second_chance_chance=0, gem_milestone_count=0, gem_streak_count=0,
    bonus_timer_duration=0, bonus_timer_gold=0, first_solver_count=0,
    first_solver_multiplier=2, steal_attempt_limit=0, steal_percent=0,
    steal_min_cap=0, steal_max_cap=0, steal_fallback_gold=0,
    steal_chest_count=0, steal_winning_chest_count=1,
    active_shield_duration=0, reactive_shield_duration=0,
    active_bonus_limit=3, permanent_bonus_cap=.10, standardized_competition=True,
)

PRESETS = {
    'intro': _BASE | dict(correct_answer_gold=25, mine_reward=15, combo_gold=5),
    'easy': _BASE | dict(
        correct_answer_gold=30, mine_reward=18, combo_gold=6,
        bonus_timer_duration=60, bonus_timer_gold=5, first_solver_count=3,
        treasure_search_reward=12, treasure_search_max_reward=20,
        treasure_double_mine_chance=.55, gem_treasure_chance=.35,
        gem_milestone_count=3,
    ),
    'normal': _BASE | dict(
        correct_answer_gold=40, mine_reward=22, combo_gold=8,
        bonus_timer_duration=60, bonus_timer_gold=5, first_solver_count=3,
        treasure_search_reward=15, treasure_search_max_reward=25,
        treasure_double_mine_chance=.65, gem_treasure_chance=.45,
        treasure_second_chance_chance=.50, treasure_steal_token_chance=.40,
        treasure_active_shield_chance=.55, gem_milestone_count=3, gem_streak_count=5,
        steal_attempt_limit=2, steal_percent=.12, steal_max_cap=25,
        steal_fallback_gold=5, steal_chest_count=5, steal_winning_chest_count=3,
        active_shield_duration=55, reactive_shield_duration=40,
    ),
    'greedy': _BASE | dict(
        correct_answer_gold=60, mine_reward=22, combo_gold=10,
        bonus_timer_duration=60, bonus_timer_gold=45, first_solver_count=3,
        treasure_search_reward=18, treasure_search_max_reward=28,
        treasure_double_mine_chance=.65, gem_treasure_chance=.55,
        treasure_second_chance_chance=.55, treasure_steal_token_chance=.70,
        treasure_active_shield_chance=.65, gem_milestone_count=2, gem_streak_count=4,
        steal_attempt_limit=5, steal_percent=.25, steal_max_cap=100,
        steal_fallback_gold=8, steal_chest_count=5, steal_winning_chest_count=3,
        active_shield_duration=45, reactive_shield_duration=40,
    ),
}
