# Classic action rewards — 19 October 2026

Deployed three files online. Mine displays the admin-configured base gold reward and existing gold icon; Steal displays the admin-configured percentage, including fractional percentages; Treasure Search displays existing chest artwork. Inline alignment preserves the existing button visibility and disabled behavior. A CSS version change refreshes cached styling.

Four rendering checks passed locally and in server staging. Two existing realtime gameplay checks passed locally. Public health, stylesheet checksum and chest image requests passed. No unfinished sessions existed before restart. All 47 database table counts were preserved. No gameplay rules or schema changed.

Rollback: `/var/backups/korephysics-game/action-buttons-20261019-152154/source-before.zip`.

Manual check: reload Classic, solve a problem, and check all offered actions in fullscreen. Set non-default mine reward and steal percentage in a test round and confirm matching labels. Mining bonuses can increase the base number shown.
