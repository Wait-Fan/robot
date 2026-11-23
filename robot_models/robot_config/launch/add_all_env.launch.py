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
node = rclpy.create_node("add_all_env")
pub = node.create_publisher(PlanningScene, "/planning_scene", 10)
time.sleep(2)

scene = PlanningScene()
scene.is_diff = True

# ==============================================
# 车厢环境
# ==============================================

# 箱撑
box1 = CollisionObject()
box1.id = "箱撑"
box1.header.frame_id = "base_link"
box1.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[0.62,1.2,0.84])]
pose1 = Pose()
pose1.position = Point(x=0.85, y=0.0, z=-0.48)
pose1.orientation = Quaternion(w=1.0)
box1.primitive_poses = [pose1]
box1.operation = CollisionObject.ADD

# 左支撑
box2 = CollisionObject()
box2.id = "左支撑"
box2.header.frame_id = "base_link"
box2.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[1.50,0.04,1.92])]
pose2 = Pose()
pose2.position = Point(x=0.44, y=-0.62, z=0.06)
pose2.orientation = Quaternion(w=1.0)
box2.primitive_poses = [pose2]
box2.operation = CollisionObject.ADD

# 右支撑
box3 = CollisionObject()
box3.id = "右支撑"
box3.header.frame_id = "base_link"
box3.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[1.50,0.04,1.92])]
pose3 = Pose()
pose3.position = Point(x=0.44, y=0.62, z=0.06)
pose3.orientation = Quaternion(w=1.0)
box3.primitive_poses = [pose3]
box3.operation = CollisionObject.ADD

# 前支撑
box4 = CollisionObject()
box4.id = "前支撑"
box4.header.frame_id = "base_link"
box4.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[0.04,1.2,1.92])]
pose4 = Pose()
pose4.position = Point(x=1.17, y=0.0, z=0.06)
pose4.orientation = Quaternion(w=1.0)
box4.primitive_poses = [pose4]
box4.operation = CollisionObject.ADD

# 天花板
box5 = CollisionObject()
box5.id = "天花板"
box5.header.frame_id = "base_link"
box5.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[1.50,1.28,0.04])]
pose5 = Pose()
pose5.position = Point(x=0.44, y=0.0, z=1.04)
pose5.orientation = Quaternion(w=1.0)
box5.primitive_poses = [pose5]
box5.operation = CollisionObject.ADD

# ==============================================
# 相机环境
# ==============================================

# 工作台
table = CollisionObject()
table.id = "工作台"
table.header.frame_id = "base_link"
table.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[0.88, 0.9, 0.9])]
pose_table = Pose()
pose_table.position = Point(x=-0.31, y=0.0, z=-0.45)
pose_table.orientation = Quaternion(w=1.0)
table.primitive_poses = [pose_table]
table.operation = CollisionObject.ADD

# 相机杆
camera_pole = CollisionObject()
camera_pole.id = "相机杆"
camera_pole.header.frame_id = "base_link"
camera_pole.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[0.06, 0.06, 1.00])]
pose_pole = Pose()
pose_pole.position = Point(x=-0.48, y=0.39, z=0.50)
pose_pole.orientation = Quaternion(w=1.0)
camera_pole.primitive_poses = [pose_pole]
camera_pole.operation = CollisionObject.ADD

# 支撑板
support = CollisionObject()
support.id = "支撑板"
support.header.frame_id = "base_link"
support.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[0.06, 0.60, 0.06])]
pose_support = Pose()
pose_support.position = Point(x=-0.48, y=0.06, z=0.94)
pose_support.orientation = Quaternion(w=1.0)
support.primitive_poses = [pose_support]
support.operation = CollisionObject.ADD

# 工业相机
cam1 = CollisionObject()
cam1.id = "工业相机box"
cam1.header.frame_id = "base_link"
cam1.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[0.06, 0.03, 0.10])]
pose_c1 = Pose()
pose_c1.position = Point(x=-0.53, y=0.0, z=0.92)
pose_c1.orientation = Quaternion(w=1.0)
cam1.primitive_poses = [pose_c1]
cam1.operation = CollisionObject.ADD

# 深度相机
depth = CollisionObject()
depth.id = "深度相机box"
depth.header.frame_id = "base_link"
depth.primitives = [SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[0.06, 0.03, 0.06])]
pose_d = Pose()
pose_d.position = Point(x=-0.43, y=0.40, z=0.2419)
pose_d.orientation = Quaternion(w=1.0)
depth.primitive_poses = [pose_d]
depth.operation = CollisionObject.ADD

# ==============================================
# 组合所有物体
# ==============================================
scene.world.collision_objects = [
    box1, box2, box3, box4, box5,
    table, camera_pole, support, cam1, depth
]

for i in range(10):
    pub.publish(scene)
    time.sleep(0.2)

print("✅ 全部环境发布成功！")
rclpy.shutdown()
'''
            ],
            output='screen'
        )
    ])
