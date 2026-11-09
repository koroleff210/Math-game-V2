# Game resource icons — 20 October 2026

Local and online: seven user-supplied transparent PNGs copied from Downloads into `app/static/classic_ui/icons/`. Downloads originals are retained.

| Filename | Supplied image suffix | Purpose |
| --- | --- | --- |
| health.png | 23_46_41-1 | Player HP and leaderboard health |
| health_lost.png | Осколки проклятого сердца | Lost player HP, replacing hearts from the right |
| attack.png | 23_46_44-3 | Damage counter and leaderboard |
| timer.png | 23_46_45-4 | Boss ability timer and Classic timer bonus |
| double_mine.png | 23_46_47-5 | Classic inventory, store, round reward preview and Treasure reveal |
| streak_small.png | 23_54_08-1 | Small combo |
| streak_medium.png | 23_46_42-2 | Medium combo |
| streak_large.png | 23_54_09-2 | Large combo |

Boss Rush flame tiers follow each round's configured reward thresholds (defaults 3 and 6). Classic uses its combo-start threshold for medium and twice that threshold for large (defaults 3 and 6); the higher Classic tier is visual only. Zero combo dims the small flame. Numeric rewards and combat mechanics are unchanged.

Full-resolution PNGs are retained. Existing `tools/build_ui_images.py` produces cached 96-pixel WebP display copies; the original seven display files total 49,812 bytes versus 11,688,872 source bytes. The additional lost-heart image is 5,164 display bytes. All three combo images preload so tier changes need no new download. Boss Rush reward explanations and victory breakdowns reuse gold icons.

Health follow-up: boss health uses an HP label, current/max numbers and its existing bar. Player health uses individual heart images (three at default HP), with lost hearts on the right; the leaderboard uses the same hearts. The number of hearts follows admin player HP settings. Fire Giant's shield count now has a dedicated visible row directly below player health, including a dimmed icon when empty, instead of being buried in the lower Bonuses row. This reuses the existing shield image and existing server shield-stack payload. No combat rules changed. Verified with a browser wrong-answer flow: two full hearts, one lost heart, no visible health fraction, shield count one.

Fullscreen layout follow-up: desktop left rail now allocates height to the ability and player panels first; the boss portrait takes the remaining space and scales the whole image without cropping. Compact spacing applies below 650 pixels of viewport height. At widths 821–1180 pixels the leaderboard stays in the third column instead of introducing an extra grid row. Victory/combination reward explanations open in a popover so expanding help does not push lower controls offscreen. Mobile layouts still scroll normally.

Browser measurements: no left-rail overflow at 1280×600, 1366×768, 1920×1080 (Fire Giant), 1024×768 (Time Wraith), and 1280×600 for each of the other five bosses. All nine cases had equal rail client/scroll heights, and the reward-help button remained inside the viewport. Expanded reward help also fit inside the 600-pixel viewport without scrolling. Raw measurements: `instance/fullscreen-measurements.json`; visual proof: `instance/boss-fullscreen-fit.png`.

Fullscreen release deployed locally and online. Server staged checks: 25 passed; all 48 database table counts preserved; health check passed. Online source backup: `/var/backups/korephysics-game/fullscreen-20261019-212308/` (UTC). Local nine Boss Rush UI smoke checks also passed.

Verification: 25 pytest checks, nine Boss Rush UI smoke checks, rendered victory JavaScript syntax check, isolated browser answers through combo 6, and public download/hash/immutable-cache verification of all seven images. Local and online health endpoints return 200.

Online source backups: `/var/backups/korephysics-game/icons-20261019-205943/` and compact combo-label follow-up `/var/backups/korephysics-game/icons-20261019-210055/` (UTC). Each staged release passed 25 checks and preserved all 48 production table counts; no migrations were needed.

Manual checks:
1. Refresh an existing game page. In Boss Rush, solve to combo 3 and 6 and check the flame in both player stats and leaderboard; a wrong answer resets/dims it.
2. Create a Boss Rush round with other reward combo thresholds and check the flame switches at those values.
3. In Classic, check Double Mine in Store, inventory and Treasure rewards; verify the hourglass disappears with the timer-bonus row when its window ends.
4. Check fullscreen at your usual display resolution and ensure counts remain beside their icons and the background atmosphere remains visible.
