import json
import tempfile
import unittest
from pathlib import Path
from ananno_phase2.ec66_model import EC66Model
from ananno_phase2.workcell_state import WorkcellState
from ananno_phase2.workcell_editor import WorkcellEditor,W

ROOT=Path(__file__).resolve().parents[1]

class ValidationSettingsTests(unittest.TestCase):
    def test_planning_controls_persist_and_restore(self):
        app=W.QApplication.instance() or W.QApplication([])
        editor=WorkcellEditor(ROOT)
        try:
            self.assertEqual(editor.box_budget.value(),30)
            editor.box_budget.setValue(45);editor.path_budget.setValue(4)
            editor.full_batch.setValue(5);editor.tiered_check.setChecked(False)
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'scene.json';editor.save_scene(path)
                cfg=json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(cfg['box_budget_seconds'],45)
                self.assertEqual(cfg['path_budget_seconds'],4)
                self.assertEqual(cfg['full_validation_batch_size'],5)
                self.assertFalse(cfg['tiered_validation'])
                other=WorkcellEditor(ROOT,scene_path=path)
                try:
                    self.assertEqual(other.box_budget.value(),45)
                    self.assertFalse(other.tiered_check.isChecked())
                finally:other.close();other.deleteLater();app.processEvents()
        finally:editor.close();editor.deleteLater();app.processEvents()

    def test_loaded_values_are_not_silently_clamped_or_overwritten(self):
        app=W.QApplication.instance() or W.QApplication([])
        state=WorkcellState.create(ROOT);state.config.update(box_budget_seconds=.05,path_budget_seconds=.05,full_validation_batch_size=10001)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scene.json';state.save(path)
            editor=WorkcellEditor(ROOT,scene_path=path)
            try:
                self.assertEqual(editor.box_budget.value(),.05)
                self.assertEqual(editor.full_batch.value(),10001)
                editor.tiered_check.setChecked(False)
                self.assertEqual(editor.state.config['box_budget_seconds'],.05)
                self.assertEqual(editor.state.config['full_validation_batch_size'],10001)
            finally:editor.close();editor.deleteLater();app.processEvents()

    def test_invalid_validation_limits_are_rejected_before_run(self):
        for key,value in [('box_budget_seconds',float('nan')),('path_budget_seconds',0),
                          ('full_validation_batch_size',0),('screen_budget_seconds',-1)]:
            state=WorkcellState.create(ROOT);state.config[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):state.validate()

if __name__=='__main__':unittest.main()

