#!/usr/bin/env python3
from launch import LaunchDescription
from launch.actions import ExecuteProcess

def generate_launch_description():
    return LaunchDescription([
        ExecuteProcess(
            cmd=[
                'python3', '-c', '''
import rclpy
import time
from moveit_msgs.msg import PlanningScene, CollisionObject
from shape_msgs.msg import SolidPrimitive
from geometry_msgs.msg import Pose

rclpy.init()
node = rclpy.create_node("add_workspace_table")
pub = node.create_publisher(PlanningScene, "/planning_scene", 10)
time.sleep(2)

scene = PlanningScene()
scene.is_diff = True

# ==================== 工作台 ====================
obj = CollisionObject()
obj.header.frame_id = "base_link"
obj.id = "table"
box = SolidPrimitive()
box.type = SolidPrimitive.BOX
box.dimensions = [0.88, 0.9, 0.9]
pose = Pose()
pose.position.x = -0.31
pose.position.y = 0.0
pose.position.z = -0.45
pose.orientation.w = 1.0
obj.primitives.append(box)
obj.primitive_poses.append(pose)
obj.operation = CollisionObject.ADD
scene.world.collision_objects.append(obj)

# ==================== 相机杆 Z - 0.04 ====================
camera_pole = CollisionObject()
camera_pole.header.frame_id = "base_link"
camera_pole.id = "camera_pole"
pole_box = SolidPrimitive()
pole_box.type = SolidPrimitive.BOX
pole_box.dimensions = [0.04, 0.04, 1.0]
pole_pose = Pose()
pole_pose.position.x = -0.48
pole_pose.position.y = 0.39
pole_pose.position.z = 0.46    # 原0.5 → 0.46
pole_pose.orientation.w = 1.0
camera_pole.primitives.append(pole_box)
camera_pole.primitive_poses.append(pole_pose)
camera_pole.operation = CollisionObject.ADD
scene.world.collision_objects.append(camera_pole)

# ==================== 支承板 Z - 0.04 ====================
support = CollisionObject()
support.header.frame_id = "base_link"
support.id = "support_beam"
beam_box = SolidPrimitive()
beam_box.type = SolidPrimitive.BOX
beam_box.dimensions = [0.04, 0.50, 0.05]
beam_pose = Pose()
beam_pose.position.x = -0.48
beam_pose.position.y = 0.12
beam_pose.position.z = 0.745   # 原0.785 → 0.745
beam_pose.orientation.w = 1.0
support.primitives.append(beam_box)
support.primitive_poses.append(beam_pose)
support.operation = CollisionObject.ADD
scene.world.collision_objects.append(support)

# ==================== 小BOX 1 Z - 0.04 ====================
obj1 = CollisionObject()
obj1.header.frame_id = "base_link"
obj1.id = "camera_box_1"
b1 = SolidPrimitive()
b1.type = SolidPrimitive.BOX
b1.dimensions = [0.06, 0.03, 0.06]
p1 = Pose()
p1.position.x = -0.53
p1.position.y = 0.31
p1.position.z = 0.75    # 原0.79 → 0.75
p1.orientation.w = 1.0
obj1.primitives.append(b1)
obj1.primitive_poses.append(p1)
obj1.operation = CollisionObject.ADD
scene.world.collision_objects.append(obj1)

# ==================== 小BOX 2 Z - 0.04 ====================
obj2 = CollisionObject()
obj2.header.frame_id = "base_link"
obj2.id = "camera_box_2"
b2 = SolidPrimitive()
b2.type = SolidPrimitive.BOX
b2.dimensions = [0.06, 0.03, 0.06]
p2 = Pose()
p2.position.x = -0.53
p2.position.y = -0.086
p2.position.z = 0.75    # 原0.79 → 0.75
p2.orientation.w = 1.0
obj2.primitives.append(b2)
obj2.primitive_poses.append(p2)
obj2.operation = CollisionObject.ADD
scene.world.collision_objects.append(obj2)

# ==================== 深度相机BOX Z - 0.04 ====================
depth_cam = CollisionObject()
depth_cam.header.frame_id = "base_link"
depth_cam.id = "depth_camera_box"
b3 = SolidPrimitive()
b3.type = SolidPrimitive.BOX
b3.dimensions = [0.06, 0.03, 0.06]
p3 = Pose()
p3.position.x = -0.45
p3.position.y = 0.39
p3.position.z = 0.758   # 原0.798 → 0.758
p3.orientation.w = 1.0
depth_cam.primitives.append(b3)
depth_cam.primitive_poses.append(p3)
depth_cam.operation = CollisionObject.ADD
scene.world.collision_objects.append(depth_cam)

for _ in range(10):
    pub.publish(scene)
    time.sleep(0.3)

print("✅ 全部障碍物 Z-0.04（下移4cm）完成！真机不会再撞！")
node.destroy_node()
rclpy.shutdown()
'''
            ],
            output='screen'
        )
    ])
