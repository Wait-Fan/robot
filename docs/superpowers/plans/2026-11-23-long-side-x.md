# Long-side-X pallet coordinates

Approved user requirement: automatically map the larger pallet dimension to X, the smaller to Y, with Z upward. A 1440x2240 pallet becomes X2240,Y1440. Existing results retain their original coordinates until recalculated.

Architecture: keep raw data readers and the Pallet constructor unchanged; add an explicit normalization operation at GUI inspection/settings, service and CLI calculation boundaries. Do not reorder box dimensions. Output coordinates and metadata describe the calculation frame. Preserve robot calibration by rotating/translating an old input-length/width pallet frame into the canonical frame, or respecting an explicitly canonical scene frame.

- [x] Write failing normalization, import, GUI, service, CLI, saved-result and robot-frame tests.
- [x] Implement explicit pallet normalization and apply consistently at calculation boundaries.
- [x] Update labels, logs and output frame metadata; preserve historical coordinates.
- [x] Adapt EC66 pallet frame using a proper right-handed rigid transform when required.
- [x] Run focused and full regression tests, inspect actual examples, review and deploy with backup.
