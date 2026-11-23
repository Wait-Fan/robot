cmake_minimum_required(VERSION 3.5)
project(robot_ec66)

# Default to C99
if(NOT CMAKE_C_STANDARD)
  set(CMAKE_C_STANDARD 99)
endif()

# Default to C++14
if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# 查找依赖
find_package(ament_cmake REQUIRED)

# 测试相关（保持默认）
if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

# 核心：安装所有必要目录（合并重复项，避免警告）
# 包含 meshes/urdf/textures/config/launch/rviz 所有目录
install(DIRECTORY
  meshes urdf textures config launch rviz
  DESTINATION share/${PROJECT_NAME}/
)

# 安装 launch 文件
install(DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

# 安装 urdf 文件（确保 URDF 也能被找到）
install(DIRECTORY urdf/
  DESTINATION share/${PROJECT_NAME}/urdf
)
# 必须放在最后
ament_package()

