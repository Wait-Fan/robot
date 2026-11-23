import tempfile
import unittest
from pathlib import Path

from ananno_phase2.models import Box, Pallet
from ananno_phase2.packer import FixedSequencePacker
from ananno_phase2.visualize import plot_result


class VisualizeTests(unittest.TestCase):
    def test_writes_non_empty_png(self):
        result = FixedSequencePacker(Pallet(4, 4, 4)).pack([Box("A", 2, 2, 2)])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plot.png"
            plot_result(result, Pallet(4, 4, 4), path, show=False)
            self.assertGreater(path.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
