import unittest
from dataclasses import replace
from tests.test_multiple_open_sides import fake_verifier
from tests.test_side_direct_approach import pose_robot,config
from tests.test_robot_2025 import item
from ananno_phase2.models import Pallet

class PalletVerificationCacheTests(unittest.TestCase):
    def setUp(self):
        self.v=fake_verifier();self.calls,self.move=pose_robot(self.v);self.approach=config(('+Z',));self.pallet=Pallet(1000,1000,10)
    def test_more_than_256_box_prefix_is_reused(self):
        items=[item(str(i),x=i,order=i+1) for i in range(300)]
        self.assertTrue(self.v.verify(items,self.pallet,self.approach)['passed']);self.calls.clear()
        result=self.v.verify(items+[item('extra',x=301,order=301)],self.pallet,self.approach)
        self.assertTrue(result['passed']);self.assertEqual(len(self.calls),6)
        self.assertEqual(result['reused_prefix_boxes'],300)

    def test_changed_pallet_is_checked_before_reusable_pallets(self):
        a=item('A');b=replace(item('B',order=2),pallet_index=1)
        self.v.verify([a,b],self.pallet,self.approach);self.calls.clear()
        c=replace(item('C',x=2,order=3),pallet_index=1)
        starts=[]
        self.v.set_log_callback(starts.append)
        result=self.v.verify([a,b,c],self.pallet,self.approach)
        self.assertTrue(result['passed']);self.assertEqual(len(self.calls),6)
        self.assertEqual(result['reused_pallets'],1);self.assertEqual(result['reused_prefix_boxes'],2)
        self.assertEqual(result['validation_pallet_order'],[2,1])
        self.assertEqual([s['box_id'] for s in result['stages'] if s['operation']=='pick'],['A','B','C'])

    def test_recent_cache_hit_survives_next_layout_insertion(self):
        a=item('A');self.v.verify([a],self.pallet,self.approach)
        for i in range(63):self.v.verify([item('other'+str(i))],self.pallet,self.approach)
        self.v.verify([a],self.pallet,self.approach)
        self.v.verify([item('new')],self.pallet,self.approach);self.calls.clear()
        report=self.v.verify([a],self.pallet,self.approach)
        self.assertEqual(len(self.calls),0);self.assertEqual(report['reused_pallets'],1)

    def test_cached_pallet_is_relabelled_without_replanning(self):
        a=item('A');self.v.verify([a],self.pallet,self.approach);self.calls.clear()
        result=self.v.verify([replace(a,pallet_index=3)],self.pallet,self.approach)
        self.assertEqual(len(self.calls),0);self.assertEqual(result['reused_pallets'],1)
        self.assertTrue(all(s['pallet']==4 for s in result['stages']))
        self.assertEqual(result['directions_by_box'][0]['pallet'],4)

if __name__=='__main__':unittest.main()

