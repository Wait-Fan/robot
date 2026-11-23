from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    # 读取 URDF 文件内容（Python 读取，无长度限制）
    urdf_path = os.path.join(get_package_share_directory('robot_ec66'), 'urdf', 'robot.ec66.urdf')
    with open(urdf_path, 'r') as f:
        robot_desc = f.read()

    # 启动 robot_state_publisher（禁用默认关节值）
    rsp_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        parameters=[
            {'robot_description': robot_desc},
            {'disable_default_joint_states': True}
        ],
        output='screen'
    )

    return LaunchDescription([rsp_node])
