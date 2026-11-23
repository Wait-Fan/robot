# Multiple open sides implementation plan

Goal: allow selecting multiple approach sides in the existing PyQt5 settings.
Architecture: retain single-direction compatibility; treat selected directions as alternatives for each box. A bounded iterative order search handles direction-dependent blockers and support prerequisites. EC66 retries each geometrically available side with state rollback and records its actual choice.
Constraints: at least one of +Z,+X,-X,+Y,-Y; default +Z; no -Z; preserve existing uncommitted path edits; no automatic Git push.
Review focus: all sides blocked, mixed per-box directions, cancel/empty selection, stale result identity, EC66 failed first side with clean rollback and cache separation.

- [x] Add failing model, sequence, CLI, UI and offline retry tests.
- [x] Implement normalized configuration and bounded alternative-side sequencing, preserving the single-side path.
- [x] Add checkbox settings and repeated CLI direction arguments, result diagnostics and stale-state detection.
- [x] Make EC66 test allowed approaches with carried box and rollback, respecting sequence budget.
- [x] Run targeted and full regressions, then deploy only changed files with backup and run actual project examples.
