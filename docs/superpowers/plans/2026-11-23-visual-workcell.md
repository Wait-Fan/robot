# Visual robot workcell editor

User asked to build the interface directly and let them select positions visually. Implement in the existing PyQt application without hardware commands. Use original URDF/STL robot geometry, interactive object selection and XY movement in both 3D and top view, signed millimetre position fields, yaw rotation, joint controls, scene save/load and explicit application to full offline robot verification.

Architecture: separate pure scene state/serialization, URDF mesh/FK geometry, QPainter scene canvas and Qt editor dialog. Pallet uses long-side-X. Robot base is pinned at the reference origin. Pickup surface defines the per-box TCP through box height and configured grasp transform. Threaded calculations receive an immutable scene snapshot. Preview alone is never described as verified.

- [x] Tests: scene/unit transforms, serialization, visual FK against EC66, signed positions, canvas picking/dragging, GUI application and actual service verification.
- [x] Implement scene state and original mesh geometry.
- [x] Implement 3D/top canvas, object drag, joint and numeric controls, save/load/apply and initial-state check.
- [x] Wire scene into workbench and background computation, including variable box-height pickup, result identities and mismatch validation.
- [x] Full regression, visual QA, fresh review, backup deployment and launch the editor for user inspection. Do not push GitHub.

2026-11-24 steering: add selectable FANUC R-2000iC/210L from supplied archive, retain EC66; user supplied 600x800mm gripper and explicitly chose provisional 250mm flange-to-contact height. Shared tool geometry and robot identity must drive preview and checking. New FANUC tests cover FK/IK, joint limits, gripper edge collision, full six-stage operation and scene roundtrip.
