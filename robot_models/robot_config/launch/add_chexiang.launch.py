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
from geometry_msgs.msg import Pose, Point, Quaternion

rclpy.init()
node = rclpy.create_node("add_chexiang")
pub = node.create_publisher(PlanningScene, "/planning_scene", 10)
time.sleep(2)

scene = PlanningScene()
scene.is_diff = True

# ========== 方块1：箱撑 ==========
box1 = CollisionObject()
box1.id = "箱撑"
box1.header.frame_id = "base_link"
box1.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[0.6,1.2,0.82])]
pose1 = Pose()
pose1.position = Point(x=0.84, y=0.0, z=-0.53)  # 原-0.49 → -0.53
pose1.orientation = Quaternion(w=1.0)
box1.primitive_poses = [pose1]
box1.operation = CollisionObject.ADD

# ========== 方块2：左支撑 ==========
box2 = CollisionObject()
box2.id = "左支撑"
box2.header.frame_id = "base_link"
box2.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[1.44,0.02,1.94])]
pose2 = Pose()
pose2.position = Point(x=0.41, y=-0.61, z=0.03)  # 原0.07 → 0.03
pose2.orientation = Quaternion(w=1.0)
box2.primitive_poses = [pose2]
box2.operation = CollisionObject.ADD

# ========== 方块3：右支撑 ==========
box3 = CollisionObject()
box3.id = "右支撑"
box3.header.frame_id = "base_link"
box3.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[1.44,0.02,1.94])]
pose3 = Pose()
pose3.position = Point(x=0.41, y=0.61, z=0.03)  # 原0.07 → 0.03
pose3.orientation = Quaternion(w=1.0)
box3.primitive_poses = [pose3]
box3.operation = CollisionObject.ADD

# ========== 方块4：前支撑 ==========
box4 = CollisionObject()
box4.id = "前支撑"
box4.header.frame_id = "base_link"
box4.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[0.02,1.2,1.94])]
pose4 = Pose()
pose4.position = Point(x=1.14, y=0.0, z=0.03)  # 原0.07 → 0.03
pose4.orientation = Quaternion(w=1.0)
box4.primitive_poses = [pose4]
box4.operation = CollisionObject.ADD

# ========== 方块5：天花板 ==========
box5 = CollisionObject()
box5.id = "天花板"
box5.header.frame_id = "base_link"
box5.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[1.44,1.2,0.02])]
pose5 = Pose()
pose5.position = Point(x=0.41, y=0.0, z=1.01)  # 原1.05 → 1.01
pose5.orientation = Quaternion(w=1.0)
box5.primitive_poses = [pose5]
box5.operation = CollisionObject.ADD

scene.world.collision_objects = [box1, box2, box3, box4, box5]

for i in range(10):
    pub.publish(scene)
    time.sleep(0.2)

print("✅ 车厢 chexiang 5个BOX 统一 Z-0.04 完成！")
rclpy.shutdown()
'''
            ],
            output='screen'
        )
    ])
