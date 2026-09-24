#pragma once

#include <memory>
#include <mutex>

#include <rclcpp/rclcpp.hpp>

#include "air_hockey_control/gantry_controller_core.hpp"
#include "air_hockey_interfaces/msg/gantry_velocity.hpp"
#include "air_hockey_interfaces/msg/mallet_command.hpp"
#include "air_hockey_interfaces/msg/mallet_pose.hpp"

namespace air_hockey_control
{

// Every ROS interface lives here. The maths lives in GantryControllerCore, which this
// class holds by value.
class GantryControllerNode : public rclcpp::Node
{
public:
  GantryControllerNode();

private:
  void on_mallet_command(const air_hockey_interfaces::msg::MalletCommand::SharedPtr msg);
  void on_mallet_pose(const air_hockey_interfaces::msg::MalletPose::SharedPtr msg);
  void publish_velocity();

  air_hockey_interfaces::msg::MalletCommand::SharedPtr latest_cmd_;
  air_hockey_interfaces::msg::MalletPose::SharedPtr latest_pose_;

  // Set when the first command arrives, so a silent strategy node can be told apart
  // from one that has never spoken.
  bool have_cmd_ = false;
  rclcpp::Time last_cmd_stamp_;

  // Table geometry is not used here: the strategy node owns the table bounds and the
  // clearance, so this node only ever sees a target it may drive to. The parameter is
  // declared so existing launch files keep working.
  double stale_timeout_s_;

  GantryControllerCore core_;

  rclcpp::Publisher<air_hockey_interfaces::msg::GantryVelocity>::SharedPtr pub_velocity_;
  rclcpp::Subscription<air_hockey_interfaces::msg::MalletCommand>::SharedPtr sub_cmd_;
  rclcpp::Subscription<air_hockey_interfaces::msg::MalletPose>::SharedPtr sub_pose_;

  rclcpp::TimerBase::SharedPtr timer_;
  std::mutex latest_mutex_;
};

}  // namespace air_hockey_control
