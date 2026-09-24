cmake_minimum_required(VERSION 3.8)
project(air_hockey_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

set(msg_files
  "msg/PuckState.msg"
  "msg/MalletCommand.msg"
  "msg/MalletPose.msg"
  "msg/GantryVelocity.msg"
)

rosidl_generate_interfaces(${PROJECT_NAME}
  ${msg_files}
)

ament_package()
