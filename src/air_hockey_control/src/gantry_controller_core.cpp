#include "air_hockey_control/gantry_controller_core.hpp"

#include <algorithm>
#include <cmath>

namespace air_hockey_control
{

float diagonal_limit_for(float max_v_axis)
{
  return max_v_axis / std::sqrt(2.0f);
}

GantryControllerCore::GantryControllerCore(float k_p, GantryLimits limits)
: k_p_(k_p), limits_(limits)
{
}

GantryVelocityCommand GantryControllerCore::compute(Vec2 target, Vec2 pose) const
{
  float vx = k_p_ * (target.x - pose.x);
  float vy = k_p_ * (target.y - pose.y);

  // The envelope is a diamond, not a circle: |vx| + |vy| <= max_v_axis.
  //
  // Reason: core XY drives belt A at vx + vy and belt B at vx - vy. Bounding the belt speed
  // bounds the reachable planar velocities to exactly |vx| + |vy| <= max_v_axis, which gives
  // max_v_axis straight along an axis (10.0) and max_v_axis / sqrt(2) on the diagonal (7.071).
  // Those are the two numbers the sizing study specifies.
  //
  // A circle of radius max_v_axis / sqrt(2) also yields 7.071 on the diagonal, but it cuts the
  // straight-line speed to 7.071 as well, which is 29 percent less than the axis speed the
  // mallet needs to reach a fast block.
  //
  // Scaling by max_v_axis / (|vx| + |vy|) preserves the commanded direction and shortens only
  // the magnitude, so the carriage keeps pointing at the target.
  const float sum = std::fabs(vx) + std::fabs(vy);
  if (sum > limits_.max_v_axis && sum > 0.0f) {
    const float s = limits_.max_v_axis / sum;
    vx *= s;
    vy *= s;
  }

  // Belt speeds are then inside the limit by construction; clamp again as an assertion of that
  // invariant, since a belt commanded past its limit is a skipped tooth, not a small error.
  GantryVelocityCommand out = to_belt_speeds(vx, vy);
  out.v_a = std::clamp(out.v_a, -limits_.max_v_axis, limits_.max_v_axis);
  out.v_b = std::clamp(out.v_b, -limits_.max_v_axis, limits_.max_v_axis);
  return out;
}

GantryVelocityCommand GantryControllerCore::to_belt_speeds(float vx, float vy)
{
  GantryVelocityCommand out;
  out.vx = vx;
  out.vy = vy;
  out.v_a = vx + vy;
  out.v_b = vx - vy;
  return out;
}

}  // namespace air_hockey_control
