import unittest

from ananno_phase2.native_scene import project_scene


class NativeSceneTests(unittest.TestCase):
    def test_foreground_small_box_is_not_hidden_by_background_large_box(self):
        pallet = {"pallet":{"length":10,"width":10,"height":10},"packed_items":[
            {"id":"A","sequence":1,"position":{"x":0,"y":0,"z":0},
             "placed_size":{"length":6,"width":5,"height":5}},
            {"id":"B","sequence":2,"position":{"x":6,"y":0,"z":0},
             "placed_size":{"length":2,"width":1,"height":3}}]}
        polygons,_,_ = project_scene(pallet,400,340)
        # 独立射线/AABB 求交：此屏幕点先命中 B 的 y=1 面，色值为 #ce9d1e。
        # A 的交点深度 -4.142，B 的交点深度 -3.445，B 明确更靠近观察者。
        def contains(points,point):
            crosses = [(b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0])
                       for a,b in zip(points,points[1:]+points[:1])]
            return all(c>=-1e-8 for c in crosses) or all(c<=1e-8 for c in crosses)
        covering = [color for _,points,color in polygons if contains(points,(262,186))]
        self.assertTrue(covering)
        self.assertEqual(covering[-1],"#ce9d1e")
