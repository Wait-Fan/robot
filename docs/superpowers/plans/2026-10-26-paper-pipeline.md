# Paper pipeline implementation plan

**Goal:** Implement both algorithm phases, the six hard/two soft constraints and small-case verification in a new selectable mode.
**Spec:** docs/full-reproduction-spec.md (user confirmed scope).
**Architecture:** Preserve FixedSequencePacker. PaperConfig configures separate paper_constraints, layer construction, GA optimizer and orchestration. Existing result/export types remain unchanged; paper diagnostics are added to JSON.
**Tech:** Python3.13/Tkinter, DEAP optional to the basic mode. No PyQt5/database.

- [x] Root: paper_config.py and paper_constraints.py, geometry/COM/contact metrics tests.
- [x] Layer domain: paper_layers.py and tests; build(boxes)->(placements,residuals,pallet_count,diagnostics).
- [x] GA domain: paper_ga.py and tests; permutation type optimizer with injected evaluator.
- [x] Root: paper_pipeline.py fixed-capacity residual placement, retries, result metadata; integration tests.
- [x] Root: add GUI mode selector, configuration and output diagnostics; preserve existing tests.
- [x] Whole-change code review; 89 tests; small-case and actual dataset checks; backup/sync E-drive and package.

Shared API: PaperConfig frozen dataclass. PaperConstraintSet(pallet,config).validate(candidate,placed,check_pattern=True)->Feasibility for local constraints; .validate_pallet(placements)->Feasibility includes final COM. PaperLayerBuilder(pallet,config,cancelled=None,log=None).build(boxes)->LayerBuildResult. GA uses optimize_types(groups:dict[str,list[Box]], evaluator, config, cancelled=None, log=None); evaluator returns TypeEvaluation(feasible,heterogeneity,compactness,payload), optimization returns best evaluation/sequence/trace.

Ruling: paper's configurable values/formula omissions are explicit defaults in spec, exported in diagnostics; results remain labelled research implementation awaiting numerical benchmark equivalence.

Verification: E-drive actual Python3.13.7 / DEAP1.4.4. Nine-box case:8 layer boxes+1 GA residual,1pallet. Order35430:15 layer boxes+120GA residuals,2pallets,all135boxes conserved,54.9081% volume utilization,70.3874% residual compactness,62.88s on this run. Basic mode remains135boxes/3pallets and imports no third-party graphics modules.
Review: canonical dimension-based type labels now agree between ungrouped CSV optimization, export and GUI; regression test watched fail then pass. No remaining verified P1/P2 review findings. This is workflow validation under documented assumptions, not author benchmark equivalence.
