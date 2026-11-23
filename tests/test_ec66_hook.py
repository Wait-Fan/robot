import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ananno_phase2.models import Box,Pallet
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2.paper_pipeline import NoPaperSolution
from ananno_phase2.robot_pipeline import RobotTwoPhasePacker

class RejectRobot:
    def __init__(self):self.calls=0
    def verify(self,*args,**kwargs):
        self.calls+=1
        return {'passed':False,'status':'unverified','reason':'test_robot_path_not_found'}

class HookTests(unittest.TestCase):
    def test_robot_rejection_occurs_inside_ga(self):
        checker=RejectRobot()
        config=PaperConfig(population_size=2,mu=2,lambda_=2,generations=1,max_stagnation=1,max_pallets=1)
        packer=RobotTwoPhasePacker(Pallet(10,10,10),config,robot_verifier=checker)
        with self.assertRaises(NoPaperSolution):packer.pack([Box('A',5,5,5)])
        self.assertGreater(checker.calls,0)
        self.assertGreater(packer.robot_rejected,0)

if __name__=='__main__':unittest.main()
