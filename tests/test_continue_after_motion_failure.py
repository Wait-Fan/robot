from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from ananno_phase2.models import Pallet,Box,PackingResult
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2.paper_ga import TypeEvaluation
from ananno_phase2.paper_layers import LayerBuildResult
from ananno_phase2.robot_approach import ApproachConfig
from ananno_phase2.robot_pipeline import RobotLayerBuilder,RobotTwoPhasePacker,_validated_sequence
from ananno_phase2.run_control import RobotPlanningIncomplete,PackingTimedOut
from tests.test_inside_out_order import item


OPS=('approach_pick','pick','lift','transfer','place','retreat')
def pending_motion(prefix):
    stages=[{'box_id':p.box.id,'pallet':p.pallet_index+1,'operation':op} for p in prefix for op in OPS]
    return {'passed':False,'status':'unverified','reason':'path_budget_exhausted','box_id':'C','failed_operation':'transfer',
            'directions_by_box':[{'box_id':p.box.id,'pallet':p.pallet_index+1} for p in prefix],
            'verified_prefix_stages':stages,'verified_prefix_boxes':len(prefix)}


class ContinueMotionTests(unittest.TestCase):
    def setup_builder(self,prefix_valid=True):
        pallet=Pallet(3,3,2);a=item('A');b=item('B',y=1,order=2);c=item('C',y=2,order=3)
        d=replace(item('D',order=4),pallet_index=1);source=[a,b,c,d];calls=[]
        class V:
            config={'robot_name':'fake'}
            def verify(self,placements,*args,**kwargs):
                names=[p.box.id for p in placements];calls.append(names)
                if names==['A','B','C']:return pending_motion([a,b])
                return {'passed':prefix_valid or names==['D'],'status':'verified' if prefix_valid else 'unverified',
                        'reason':'','assumptions':[]}
        owner=RobotTwoPhasePacker(pallet,approach=ApproachConfig('+Z',outside_side='-Y'),robot_verifier=V(),seal_verified_pallets=True)
        builder=owner._make_layer_builder(log=lambda message:None)
        raw=LayerBuildResult(source,[],2,{'layer_placements':[{'pallet_index':0,'kind':'full'},{'pallet_index':1,'kind':'full'}]})
        return owner,builder,raw,source,calls

    def test_phase1_keeps_safe_prefix_defers_tail_and_continues_next_pallet(self):
        owner,builder,raw,source,calls=self.setup_builder()
        with patch('ananno_phase2.paper_layers.PaperLayerBuilder.build',return_value=raw):result=builder.build([p.box for p in source])
        self.assertEqual([p.box.id for p in result.placements],['A','B','D'])
        self.assertEqual([p.id for p in result.residuals],['C']);self.assertIn(['D'],calls);self.assertIn(['A','B'],calls)
        self.assertEqual(owner._sealed_pallet_indices,{0,1})
        self.assertEqual(result.diagnostics['robot_retained_prefixes'][0]['retained_boxes'],2)
        self.assertEqual(sorted([p.box.id for p in result.placements]+[b.id for b in result.residuals]),['A','B','C','D'])

    def test_prefix_not_retained_if_prefix_verification_does_not_pass(self):
        owner,builder,raw,source,calls=self.setup_builder(prefix_valid=False)
        with patch('ananno_phase2.paper_layers.PaperLayerBuilder.build',return_value=raw):result=builder.build([p.box for p in source])
        self.assertEqual([p.box.id for p in result.placements],['D'])
        self.assertEqual({b.id for b in result.residuals},{'A','B','C'})

    def test_local_box_budget_is_recoverable_global_timeout_still_propagates(self):
        a=item('A');pallet=Pallet(1,1,1);cfg=ApproachConfig()
        v=SimpleNamespace(verify=lambda *a,**kw:{'passed':False,'status':'unverified','reason':'box_validation_budget_exhausted'})
        with self.assertRaises(RobotPlanningIncomplete) as caught:_validated_sequence([a],pallet,PaperConfig(),cfg,v)
        self.assertIsNotNone(caught.exception.motion_report)
        v.verify=lambda *a,**kw:(_ for _ in ()).throw(PackingTimedOut('global deadline'))
        with self.assertRaises(PackingTimedOut):_validated_sequence([a],pallet,PaperConfig(),cfg,v)

    def test_ga_tries_next_candidate_after_first_motion_pending(self):
        cfg=replace(PaperConfig(),population_size=6,mu=4,lambda_=2,generations=1,max_stagnation=1)
        v=SimpleNamespace(tiered_validation=True,config={'full_validation_batch_size':1})
        packer=RobotTwoPhasePacker(Pallet(3,3,2),cfg,robot_verifier=v)
        placements=[item('A')];payload=PackingResult(placements,[],packer.pallet);count=[0]
        def validate(*args,**kw):
            count[0]+=1
            if count[0]==1:raise RobotPlanningIncomplete('test pending')
            return placements,{'passed':True},{'passed':True}
        groups={k:[Box(k,1,1,1)] for k in 'ABC'}
        with patch('ananno_phase2.robot_pipeline._validated_sequence',side_effect=validate):
            result=packer._optimize_types(groups,lambda seq:TypeEvaluation(True,1,1,payload))
        self.assertIsNotNone(result.best);self.assertGreaterEqual(count[0],2)
        self.assertEqual(packer.robot_rejected,0)

    def test_sealed_unused_volume_is_not_credited_to_residual_capacity(self):
        packer=RobotTwoPhasePacker(Pallet(3,1,1));initial=[item('A')]
        packer._sealed_pallet_indices={0};self.assertEqual(packer._free_existing_volume(initial,1),0)
        packer._sealed_pallet_indices=set();self.assertEqual(packer._free_existing_volume(initial,1),2)

    def test_all_pending_candidates_are_tried_but_never_published(self):
        from ananno_phase2.paper_ga import optimize_types
        cfg=replace(PaperConfig(),population_size=6,mu=4,lambda_=2,generations=1,max_stagnation=1)
        checked=[];groups={key:[Box(key,1,1,1)] for key in 'ABC'}
        def validation(evaluation):
            checked.append(evaluation);return replace(evaluation,validation_status='motion_pending')
        result=optimize_types(groups,lambda seq:TypeEvaluation(True,1,1,list(seq)),cfg,validate_candidate=validation)
        self.assertIsNone(result.best);self.assertGreaterEqual(len(checked),2)

    def test_prefix_remains_sealed_when_other_pallets_allow_refilling(self):
        owner,builder,raw,source,calls=self.setup_builder();owner.seal_verified_pallets=False
        with patch('ananno_phase2.paper_layers.PaperLayerBuilder.build',return_value=raw):result=builder.build([p.box for p in source])
        self.assertEqual(owner._sealed_pallet_indices,{0})
        self.assertEqual([p.id for p in result.residuals],['C'])

    def test_end_to_end_tail_moves_to_new_pallet_without_losing_any_box(self):
        owner,builder,raw,source,calls=self.setup_builder()
        owner.config=replace(owner.config,population_size=4,mu=2,lambda_=2,generations=1,max_stagnation=1,max_pallets=4)
        with patch('ananno_phase2.paper_layers.PaperLayerBuilder.build',return_value=raw):
            result=owner.pack([p.box for p in source])
        self.assertEqual(sorted(p.box.id for p in result.placements),['A','B','C','D'])
        self.assertEqual(len(result.unplaced),0);self.assertEqual(result.pallet_count,3)
        places={p.box.id:p.pallet_index for p in result.placements}
        self.assertEqual(places['A'],places['B']);self.assertNotEqual(places['A'],places['C'])
        self.assertTrue(owner.robot_diagnostics['ik_verified'])

if __name__=='__main__':unittest.main()
