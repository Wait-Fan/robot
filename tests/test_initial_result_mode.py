import unittest
from ananno_phase2.robot_pipeline import RobotTwoPhasePacker
from ananno_phase2.models import Box,Pallet
from ananno_phase2.robot_approach import ApproachConfig
from tests.test_inside_out_order import item

class InitialResultModeTests(unittest.TestCase):
    def test_sealed_pallets_cannot_receive_residual_boxes(self):
        packer=RobotTwoPhasePacker(Pallet(3,1,2),approach=ApproachConfig('+Z',outside_side='+Y'),seal_verified_pallets=True)
        packer._sealed_pallet_indices={0}
        result=packer.evaluate_sequence({'B':[Box('B',1,1,1,1,'B')]},['B'],[item('A')],2)
        self.assertTrue(result.feasible)
        self.assertEqual(next(p for p in result.payload.placements if p.box.id=='B').pallet_index,1)
    def test_workbench_setting_is_forwarded_and_can_be_disabled(self):
        from pathlib import Path
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench,W,C
        app=W.QApplication.instance() or W.QApplication([])
        window=RobotWorkbench(Path(__file__).resolve().parents[1],restore_workcell=False)
        try:
            self.assertTrue(window._job_options()['robot_seal_verified_pallets'])
            def edit():
                dialog=app.activeModalWidget();check=dialog.findChild(W.QCheckBox,'initialResultFirst')
                self.assertTrue(check.isChecked());check.setChecked(False)
                dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.Ok).click()
            C.QTimer.singleShot(0,edit);window.show_settings()
            self.assertFalse(window._job_options()['robot_seal_verified_pallets'])
        finally:window.close();window.deleteLater();app.processEvents()

    def test_default_mode_still_allows_filling_existing_pallet(self):
        packer=RobotTwoPhasePacker(Pallet(3,1,2),approach=ApproachConfig('+Z',outside_side='+Y'))
        result=packer.evaluate_sequence({'B':[Box('B',1,1,1,1,'B')]},['B'],[item('A')],1)
        self.assertTrue(result.feasible)
        self.assertEqual(next(p for p in result.payload.placements if p.box.id=='B').pallet_index,0)

if __name__=='__main__':unittest.main()
