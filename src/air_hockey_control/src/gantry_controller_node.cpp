#include "air_hockey_control/gantry_controller_node.hpp"

#include <chrono>
#include <functional>

using namespace std::chrono_literals;

namespace air_hockey_control
{

GantryControllerNode::GantryControllerNode()
: Node("gantry_controller_node"),
  stale_timeout_s_(0.25),
  core_(4.0f, GantryLimits{10.0f, 7.07f})
{
  declare_parameter("k_p", 4.0);
  // Declared for compatibility with the existing run command. The controller does not bound
  // the target against the table: the strategy node owns the table geometry.
  declare_parameter("table_length_m", 1.2192);
  declare_parameter("max_v_axis", 10.0);
  declare_parameter("max_v_diag", 7.07);
  declare_parameter("publish_rate_hz", 200.0);
  declare_parameter("stale_timeout_s", 0.25);

  const double k_p = get_parameter("k_p").as_double();
  const double max_v_axis = get_parameter("max_v_axis").as_double();
  const double max_v_diag = get_parameter("max_v_diag").as_double();
  const double publish_rate_hz = get_parameter("publish_rate_hz").as_double();
  stale_timeout_s_ = get_parameter("stale_timeout_s").as_double();

  core_ = GantryControllerCore(
    static_cast<float>(k_p),
    GantryLimits{static_cast<float>(max_v_axis), static_cast<float>(max_v_diag)});

  // The diagonal speed is a consequence of the belt limit: 10 m/s of belt gives 7.071 on the
  // diagonal, and no separate diagonal cap is needed to get it. A max_v_diag that disagrees
  // means the parameter was set on a different assumption, so say so rather than ignore it.
  const double implied_diag = diagonal_limit_for(static_cast<float>(max_v_axis));
  if (std::fabs(max_v_diag - implied_diag) > 0.05) {
    RCLCPP_WARN(
      get_logger(),
      "max_v_diag=%.3f disagrees with the %.3f implied by max_v_axis=%.3f; the belt limit "
      "governs, so the diagonal speed will be %.3f",
      max_v_diag, implied_diag, max_v_axis, implied_diag);
  }

  pub_velocity_ = create_publisher<air_hockey_interfaces::msg::GantryVelocity>(
    "/air_hockey/gantry_velocity", 10);

  sub_cmd_ = create_subscription<air_hockey_interfaces::msg::MalletCommand>(
    "/air_hockey/mallet_command", 10,
    std::bind(&GantryControllerNode::on_mallet_command, this, std::placeholders::_1));

  sub_pose_ = create_subscription<air_hockey_interfaces::msg::MalletPose>(
    "/air_hockey/mallet_pose", 10,
    std::bind(&GantryControllerNode::on_mallet_pose, this, std::placeholders::_1));

  const auto period = std::chrono::duration<double>(1.0 / publish_rate_hz);
  timer_ = create_wall_timer(
    std::chrono::duration_cast<std::chrono::nanoseconds>(period),
    std::bind(&GantryControllerNode::publish_velocity, this));

  RCLCPP_INFO(
    get_logger(), "gantry_controller_node ready at %.0f Hz, k_p=%.3f", publish_rate_hz, k_p);
}

void GantryControllerNode::on_mallet_command(
  const air_hockey_interfaces::msg::MalletCommand::SharedPtr msg)
{
  std::scoped_lock lock(latest_mutex_);
  latest_cmd_ = msg;
  last_cmd_stamp_ = now();
  have_cmd_ = true;
}

void GantryControllerNode::on_mallet_pose(const air_hockey_interfaces::msg::MalletPose::SharedPtr msg)
{
  std::scoped_lock lock(latest_mutex_);
  latest_pose_ = msg;
}

void GantryControllerNode::publish_velocity()
{
  air_hockey_interfaces::msg::MalletCommand::SharedPtr cmd;
  air_hockey_interfaces::msg::MalletPose::SharedPtr pose;
  bool has_cmd = false;
  rclcpp::Time last_stamp;
  {
    std::scoped_lock lock(latest_mutex_);
    cmd = latest_cmd_;
    pose = latest_pose_;
    has_cmd = have_cmd_;
    last_stamp = last_cmd_stamp_;
  }

  if (!pose) {
    return;
  }

  // A strategy node that dies, or a link that stalls, must not leave the gantry
  // latched at its last commanded speed, so a silent input is commanded to zero.
  const double age = has_cmd ? (now() - last_stamp).seconds() : stale_timeout_s_ * 2.0;

  GantryVelocityCommand out;
  if (age > stale_timeout_s_) {
    out = GantryControllerCore::to_belt_speeds(0.0f, 0.0f);
    if (has_cmd) {
      RCLCPP_WARN_THROTTLE(
        get_logger(), *get_clock(), 2000, "mallet_command is %.3f s old, commanding stop", age);
    }
  } else {
    out = core_.compute(
      Vec2{static_cast<float>(cmd->target_x), static_cast<float>(cmd->target_y)},
      Vec2{static_cast<float>(pose->x), static_cast<float>(pose->y)});
  }

  air_hockey_interfaces::msg::GantryVelocity msg;
  msg.vx = out.vx;
  msg.vy = out.vy;
  msg.v_a = out.v_a;
  msg.v_b = out.v_b;

  pub_velocity_->publish(msg);
}

}  // namespace air_hockey_control

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<air_hockey_control::GantryControllerNode>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
