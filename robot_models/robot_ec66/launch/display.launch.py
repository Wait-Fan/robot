import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    pkg_robot_ec66 = get_package_share_directory('robot_ec66')
    urdf_file_path = os.path.join(pkg_robot_ec66, 'urdf', 'robot.ec66.urdf')
    # 配置文件路径（你刚才保存的）
    rviz_config_path = os.path.join(pkg_robot_ec66, 'config', 'robot_model.rviz')

    return LaunchDescription([
        # 1. 发布URDF和TF树（机械臂坐标核心）
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            arguments=[urdf_file_path]
        ),
        # 2. 带GUI关节控制面板（可拖动关节，必带）
        Node(
            package='joint_state_publisher_gui',
            executable='joint_state_publisher_gui',
            name='joint_state_publisher_gui'
        ),
        # 3. 启动RVIZ2 + 自动加载配置文件（不用手动配置）
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            output='screen',
            arguments=['-d', rviz_config_path]
        )
    ])
