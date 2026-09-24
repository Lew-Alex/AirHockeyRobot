cmake_minimum_required(VERSION 3.8)
project(air_hockey_control)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
  set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(air_hockey_interfaces REQUIRED)

# The velocity law, with no ROS linked against it. Keeping it in its own library is what lets
# the tests below run against the maths alone, and is why the two source files are split.
add_library(gantry_controller_core src/gantry_controller_core.cpp)
target_include_directories(gantry_controller_core PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)
target_compile_features(gantry_controller_core PUBLIC cxx_std_17)

add_executable(gantry_controller_node src/gantry_controller_node.cpp)
target_link_libraries(gantry_controller_node gantry_controller_core)
ament_target_dependencies(gantry_controller_node
  rclcpp
  air_hockey_interfaces
)

install(TARGETS gantry_controller_node
  DESTINATION lib/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()

  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_gantry_controller_core test/test_gantry_controller_core.cpp)
  target_link_libraries(test_gantry_controller_core gantry_controller_core)
endif()

ament_package()
