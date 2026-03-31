document.addEventListener('DOMContentLoaded', function () {
  bindDetailsTriggers();
  initClassicSessionForm();
});

function bindDetailsTriggers() {
  document.querySelectorAll('[data-open-details]').forEach(function (button) {
    button.addEventListener('click', function () {
      const targetId = button.getAttribute('data-open-details');
      const details = document.getElementById(targetId);
      if (!details) {
        return;
      }
      details.open = true;
      details.scrollIntoView({ behavior: 'smooth', block: 'start' });
      const focusTarget = details.querySelector('input, select, textarea, button');
      if (focusTarget) {
        focusTarget.focus();
      }
    });
  });
}

function initClassicSessionForm() {
  const form = document.querySelector('[data-classic-session-form]');
  if (!form) {
    return;
  }

  const fields = {
    problemSet: form.querySelector('[name="problem_set_id"]'),
    group: form.querySelector('[name="group_id"]'),
    label: form.querySelector('[name="label"]'),
    treasureMin: form.querySelector('[name="treasure_search_reward"]'),
    treasureMax: form.querySelector('[name="treasure_search_max_reward"]'),
    timerDuration: form.querySelector('[name="bonus_timer_duration"]'),
    timerGold: form.querySelector('[name="bonus_timer_gold"]'),
    firstSolverCount: form.querySelector('[name="first_solver_count"]'),
    firstSolverMultiplier: form.querySelector('[name="first_solver_multiplier"]'),
    gemMilestone: form.querySelector('[name="gem_milestone_count"]'),
    gemStreak: form.querySelector('[name="gem_streak_count"]'),
    gemTreasureChance: form.querySelector('[name="gem_treasure_chance"]'),
    treasureStealChance: form.querySelector('[name="treasure_steal_token_chance"]'),
    treasureShieldChance: form.querySelector('[name="treasure_active_shield_chance"]'),
    treasureSecondChance: form.querySelector('[name="treasure_second_chance_chance"]'),
    stealPercent: form.querySelector('[name="steal_percent"]'),
    stealMinCap: form.querySelector('[name="steal_min_cap"]'),
    stealMaxCap: form.querySelector('[name="steal_max_cap"]'),
    chestCount: form.querySelector('[name="steal_chest_count"]'),
    winningChestCount: form.querySelector('[name="steal_winning_chest_count"]')
  };

  const outputs = {
    session: form.querySelector('[data-review="session"]'),
    treasureRange: form.querySelector('[data-review="treasure-range"]'),
    bonusSources: form.querySelector('[data-review="bonus-sources"]'),
    sideRewards: form.querySelector('[data-review="side-rewards"]'),
    steal: form.querySelector('[data-review="steal"]'),
    disabledStates: form.querySelector('[data-review="disabled-states"]'),
    warnings: form.querySelector('[data-review="warnings"]')
  };

  Object.values(fields).filter(Boolean).forEach(function (field) {
    field.addEventListener('input', renderClassicReview);
    field.addEventListener('change', renderClassicReview);
  });

  renderClassicReview();

  function renderClassicReview() {
    const treasureMin = toNumber(fields.treasureMin, 0);
    const treasureMax = toNumber(fields.treasureMax, 0);
    const timerDuration = toNumber(fields.timerDuration, 0);
    const timerGold = toNumber(fields.timerGold, 0);
    const firstSolverCount = toNumber(fields.firstSolverCount, 0);
    const firstSolverMultiplier = toNumber(fields.firstSolverMultiplier, 0);
    const gemMilestone = toNumber(fields.gemMilestone, 0);
    const gemStreak = toNumber(fields.gemStreak, 0);
    const gemTreasureChance = toNumber(fields.gemTreasureChance, 0);
    const treasureStealChance = toNumber(fields.treasureStealChance, 0);
    const treasureShieldChance = toNumber(fields.treasureShieldChance, 0);
    const treasureSecondChance = toNumber(fields.treasureSecondChance, 0);
    const chestCount = toNumber(fields.chestCount, 0);
    const winningChestCount = toNumber(fields.winningChestCount, 0);
    const stealPercent = toNumber(fields.stealPercent, 0);
    const stealMinCap = toNumber(fields.stealMinCap, 0);
    const stealMaxCap = toNumber(fields.stealMaxCap, 0);

    if (outputs.session) {
      outputs.session.textContent = buildSessionSummary(fields.problemSet, fields.group, fields.label);
    }
    if (outputs.treasureRange) {
      outputs.treasureRange.textContent = 'Treasure gold awards between ' + treasureMin + ' and ' + treasureMax + ' gold.';
    }
    if (outputs.bonusSources) {
      outputs.bonusSources.textContent = buildBonusSummary(timerDuration, timerGold, firstSolverCount, firstSolverMultiplier, gemMilestone, gemStreak);
    }
    if (outputs.sideRewards) {
      outputs.sideRewards.textContent = buildTreasureChestSummary(
        gemTreasureChance,
        treasureStealChance,
        treasureShieldChance,
        treasureSecondChance
      );
    }
    if (outputs.steal) {
      outputs.steal.textContent = buildStealSummary(stealPercent, stealMinCap, stealMaxCap, chestCount, winningChestCount);
    }
    if (outputs.disabledStates) {
      outputs.disabledStates.textContent = buildDisabledStates(timerDuration, firstSolverCount, chestCount, stealMaxCap);
    }

    const warnings = [];
    if (treasureMax < treasureMin) {
      warnings.push('Treasure max reward is below the minimum reward.');
    }
    if (chestCount > 0 && winningChestCount > chestCount) {
      warnings.push('Winning chest count is greater than the total chest count.');
    }

    if (outputs.warnings) {
      outputs.warnings.innerHTML = warnings.map(function (warning) {
        return '<li>' + escapeHtml(warning) + '</li>';
      }).join('');
    }
  }
}

function buildSessionSummary(problemSet, group, label) {
  const problemSetText = selectedOptionText(problemSet) || 'No problem set selected';
  const groupText = selectedOptionText(group) || 'Open session';
  const labelValue = label && label.value.trim() ? '"' + label.value.trim() + '"' : 'auto-generated label';
  return problemSetText + ' | ' + groupText + ' | ' + labelValue;
}

function buildBonusSummary(timerDuration, timerGold, firstSolverCount, firstSolverMultiplier, gemMilestone, gemStreak) {
  const parts = [];
  if (timerDuration > 0) {
    parts.push('timer bonus enabled (' + timerGold + ' gold for ' + timerDuration + 's)');
  }
  if (firstSolverCount > 0) {
    parts.push('first-solver bonus enabled (' + firstSolverCount + ' slots at x' + firstSolverMultiplier + ')');
  }
  if (gemMilestone > 0) {
    parts.push('gems from milestones every ' + gemMilestone + ' solves');
  }
  if (gemStreak > 0) {
    parts.push('gems from streaks every ' + gemStreak + ' correct answers');
  }
  return parts.length ? parts.join('. ') + '.' : 'No bonus sources are currently enabled.';
}

function buildStealSummary(stealPercent, stealMinCap, stealMaxCap, chestCount, winningChestCount) {
  const percentText = Math.round(stealPercent * 1000) / 10;
  const capText = stealMaxCap === -1 ? 'no max cap' : 'max ' + stealMaxCap + ' gold';
  const miniGameText = chestCount === 0
    ? 'mini-game disabled'
    : chestCount + ' chests with ' + winningChestCount + ' winning chest' + (winningChestCount === 1 ? '' : 'es');
  return 'Steal takes about ' + percentText + '% of target gold, minimum ' + stealMinCap + ', ' + capText + '; ' + miniGameText + '.';
}

function buildTreasureChestSummary(gemTreasureChance, treasureStealChance, treasureShieldChance, treasureSecondChance) {
  const parts = [];
  if (gemTreasureChance > 0) {
    parts.push('Gem chest ' + formatChance(gemTreasureChance));
  }
  if (treasureStealChance > 0) {
    parts.push('Steal Token chest ' + formatChance(treasureStealChance));
  }
  if (treasureShieldChance > 0) {
    parts.push('Shield Token chest ' + formatChance(treasureShieldChance));
  }
  if (treasureSecondChance > 0) {
    parts.push('Second Chance chest ' + formatChance(treasureSecondChance));
  }
  if (!parts.length) {
    return 'No treasure bonus chests are currently enabled.';
  }
  return parts.join('. ') + '. Each eligible chest fills independently, and only the selected chest can grant its reward.';
}

function buildDisabledStates(timerDuration, firstSolverCount, chestCount, stealMaxCap) {
  const states = [];
  states.push(timerDuration === 0 ? 'Timer bonus disabled.' : 'Timer bonus active.');
  states.push(firstSolverCount === 0 ? 'First-solver bonus disabled.' : 'First-solver bonus active.');
  states.push(chestCount === 0 ? 'Steal mini-game disabled; winning chest count is ignored.' : 'Steal mini-game active.');
  states.push(stealMaxCap === -1 ? 'Steal max cap disabled.' : 'Steal max cap enforced.');
  return states.join(' ');
}

function toNumber(field, fallback) {
  if (!field) {
    return fallback;
  }
  const value = Number(field.value);
  return Number.isFinite(value) ? value : fallback;
}

function formatChance(value) {
  return (Math.round(value * 1000) / 1000).toFixed(3);
}

function selectedOptionText(select) {
  if (!select || select.selectedIndex < 0) {
    return '';
  }
  return select.options[select.selectedIndex].text;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
