import unittest,time
from ananno_phase2.robot_execution_constraints import pattern_connected
from ananno_phase2.paper_constraints import pattern_aligned
from ananno_phase2.models import Pallet
from ananno_phase2.packer import PackingCancelled
from tests.test_inside_out_order import item

class PatternConnectivityTests(unittest.TestCase):
    def test_long_row_is_indexed_not_rescanned(self):
        started=time.perf_counter()
        self.assertTrue(pattern_connected([item(str(i),x=i) for i in range(100)],Pallet(101,5,5)))
        self.assertLess(time.perf_counter()-started,2.)
    def test_can_cancel_vertex_graph_construction(self):
        with self.assertRaises(PackingCancelled):
            pattern_connected([item('a')],Pallet(3,3,3),cancelled=lambda:True)
    def test_connectivity_preserves_eps_and_disconnected_components(self):
        for gap in (0,5e-10,2e-9,.2):
            boxes=[item('a'),item('b',x=1+gap),item('c',x=2+gap)]
            remaining=list(boxes);connected=[]
            while remaining:
                ready=[b for b in remaining if pattern_aligned(b,connected,Pallet(5,5,5))]
                if not ready:break
                connected.extend(ready);remaining=[b for b in remaining if b not in ready]
            self.assertEqual(pattern_connected(boxes,Pallet(5,5,5)),not remaining)

if __name__=='__main__':unittest.main()
