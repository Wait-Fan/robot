# Whole-pallet ordering and preplacement motion implementation plan

> Executed inline with superpowers:executing-plans; one fresh whole-change review.

**Goal:** cross-layer inside-out placement, shared occupied-edge suction grasp, elevated preplacement and smooth checked joint replay.

**Architecture:** support/depth DAG; one per-box grasp transform; bounded RRT-Connect candidate comparison; collision-checked shortcut and C2 quintic trajectories.

**Tech stack:** existing Python/numpy/PyQt5 and robot runtime.

**Spec:** [Behavior and settings](../../跨层顺序与预放置轨迹.md).

## Constraints

- User requested code changes without a new production packing or real-model planning trial.
- Preserve current scene, previous results and existing dirty work. No commit/push.
- Align the suction plate's two occupied-side edges with the corresponding box edges; overhang faces outward.
- Reject support/depth dependency cycles rather than silently relaxing inside-out order.
- Replay the same curves and grasp transforms checked during computation; preserve legacy cubic results.

## Implementation and verification

- [x] RED/GREEN regressions for cross-layer columns, wide supports and dependency cycles.
- [x] Shared grasp transform in filter, endpoint screen, full planner, attachment and replay; Z90 and occupied-side tests.
- [x] Short Z lift, elevated pre-place, vertical/diagonal descent, complete candidate cost comparison with rollback.
- [x] C2 quintic timing with velocity/acceleration extrema, limit checking and curve collision checks; legacy replay compatibility.
- [x] GUI/CLI defaults and adjustable lift/preplace/grasp settings; screenshot visibility inspection.
- [x] Reviewed and corrected mapped-pallet filter transform mismatch with RED/GREEN test.
- [x] Selected deterministic, cache, geometric-fixture and UI regressions; excluded real-model IK/path/full packing trials.
- [x] Fresh reviewer: no remaining Important/Critical findings.
- [ ] Apply reviewed files with backup/hash guards; verify installed source and preserved scene.

The future real-model packing trial remains explicitly deferred by the user. Test success does not assert that the new settings already produce a physically feasible 668-box result.
