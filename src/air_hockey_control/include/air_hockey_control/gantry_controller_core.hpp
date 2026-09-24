#pragma once

namespace air_hockey_control
{

struct Vec2
{
  float x;
  float y;
};

struct GantryLimits
{
  // Belt speed limit, which is also the straight-line speed limit of the carriage.
  float max_v_axis;
  // Reported for the startup consistency check only. See the note in the core .cpp.
  float max_v_diag;
};

// Named ...Command rather than GantryVelocity so it cannot be confused with
// air_hockey_interfaces::msg::GantryVelocity at a call site.
struct GantryVelocityCommand
{
  float vx;
  float vy;
  float v_a;
  float v_b;
};

// The diagonal speed the belt limit implies: max_v_axis / sqrt(2), which is 7.071 for a
// 10 m/s belt limit. Exposed so the node can tell a mis-set max_v_diag from a consistent one.
float diagonal_limit_for(float max_v_axis);

// Pure velocity law for the gantry: the proportional term, the speed envelope, and the CoreXY
// mapping from planar velocity to belt speeds. No rclcpp calls, no parameters, no clocks. The
// node owns all of that and forwards numbers here, which is what makes this testable without a
// running ROS graph.
class GantryControllerCore
{
public:
  GantryControllerCore(float k_p, GantryLimits limits);

  // Proportional law on the position error, then the envelope, then the belt mapping.
  GantryVelocityCommand compute(Vec2 target, Vec2 pose) const;

  // CoreXY forward mapping: vA = vx + vy, vB = vx - vy.
  static GantryVelocityCommand to_belt_speeds(float vx, float vy);

private:
  float k_p_;
  GantryLimits limits_;
};

}  // namespace air_hockey_control
