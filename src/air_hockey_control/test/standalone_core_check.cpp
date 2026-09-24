// Core-only checks for the gantry velocity law, with no ROS and no gtest, so the maths can be
// verified on a machine that has a C++ compiler but no ROS 2 install:
//
//   clang++ -std=c++17 -I src/air_hockey_control/include \
//     src/air_hockey_control/src/gantry_controller_core.cpp \
//     src/air_hockey_control/test/standalone_core_check.cpp -o /tmp/core_check && /tmp/core_check
//
// The gtest version of these cases, for `colcon test`, is in test_gantry_controller_core.cpp.

#include <algorithm>
#include <cmath>
#include <cstdio>

#include "air_hockey_control/gantry_controller_core.hpp"

namespace
{

int failures = 0;

void expect_close(const char * label, float got, float want, float tol = 1e-3f)
{
  const bool ok = std::fabs(got - want) <= tol;
  if (!ok) {
    ++failures;
  }
  std::printf("%-48s got %8.4f  want %8.4f  %s\n", label, got, want, ok ? "ok" : "FAIL");
}

void expect_true(const char * label, bool ok)
{
  if (!ok) {
    ++failures;
  }
  std::printf("%-48s %s\n", label, ok ? "ok" : "FAIL");
}

}  // namespace

int main()
{
  using air_hockey_control::GantryControllerCore;
  using air_hockey_control::GantryLimits;
  using air_hockey_control::Vec2;

  const GantryLimits limits{10.0f, air_hockey_control::diagonal_limit_for(10.0f)};

  {
    // Small error, inside the envelope: v = k_p * error, and the belt speeds follow.
    GantryControllerCore core(4.0f, limits);
    const auto out = core.compute(Vec2{0.5f, 0.5f}, Vec2{0.0f, 0.0f});
    expect_close("error 0.5,0.5 -> vx", out.vx, 2.0f);
    expect_close("error 0.5,0.5 -> vy", out.vy, 2.0f);
    expect_close("error 0.5,0.5 -> v_a = vx + vy", out.v_a, 4.0f);
    expect_close("error 0.5,0.5 -> v_b = vx - vy", out.v_b, 0.0f);
  }

  {
    // Straight along an axis: 4.0 * 5.0 = 20 requested, the full 10.0 is available, and both
    // belts see exactly the limit. This is the case the scaffold's circle cap got wrong.
    GantryControllerCore core(4.0f, limits);
    const auto out = core.compute(Vec2{5.0f, 0.0f}, Vec2{0.0f, 0.0f});
    expect_close("axis: speed reaches 10", out.vx, 10.0f);
    expect_close("axis: vy stays 0", out.vy, 0.0f);
    expect_close("axis: v_a at the limit", out.v_a, 10.0f);
    expect_close("axis: v_b at the limit", out.v_b, 10.0f);
  }

  {
    // Equal diagonal: 8,8 is 16 long in the diamond metric, so it scales by 0.625 to 5,5.
    // The magnitude is then 7.071 and one belt is at the limit while the other is idle.
    GantryControllerCore core(4.0f, limits);
    const auto out = core.compute(Vec2{2.0f, 2.0f}, Vec2{0.0f, 0.0f});
    expect_close("diagonal: vx scales to 5", out.vx, 5.0f);
    expect_close("diagonal: vy scales to 5", out.vy, 5.0f);
    expect_close("diagonal: magnitude is 7.071", std::sqrt(out.vx * out.vx + out.vy * out.vy), 7.071f);
    expect_close("diagonal: v_a at the limit", out.v_a, 10.0f);
    expect_close("diagonal: v_b idle", out.v_b, 0.0f);
  }

  {
    // Opposite diagonal: the sign survives scaling.
    GantryControllerCore core(4.0f, limits);
    const auto out = core.compute(Vec2{-2.0f, 2.0f}, Vec2{0.0f, 0.0f});
    expect_close("opposite diagonal: vx", out.vx, -5.0f);
    expect_close("opposite diagonal: vy", out.vy, 5.0f);
    expect_close("opposite diagonal: v_a", out.v_a, 0.0f);
    expect_close("opposite diagonal: v_b", out.v_b, -10.0f);
  }

  {
    // No error is no motion, not a small drift.
    GantryControllerCore core(4.0f, limits);
    const auto out = core.compute(Vec2{0.3f, -0.2f}, Vec2{0.3f, -0.2f});
    expect_close("zero error: vx", out.vx, 0.0f);
    expect_close("zero error: vy", out.vy, 0.0f);
  }

  {
    // The mapping on its own, the pair of numbers the belts actually see.
    const auto out = GantryControllerCore::to_belt_speeds(3.0f, 1.0f);
    expect_close("mapping 3,1: v_a = 4", out.v_a, 4.0f);
    expect_close("mapping 3,1: v_b = 2", out.v_b, 2.0f);
    expect_close("mapping 3,1: vx passthrough", out.vx, 3.0f);
    expect_close("mapping 3,1: vy passthrough", out.vy, 1.0f);
  }

  {
    // The invariant that matters for hardware: no command, in any direction, can ask a belt for
    // more than the limit. A saturating command is used so the envelope is fully exercised.
    GantryControllerCore core(4.0f, limits);
    float worst_belt = 0.0f;
    float axial_reach = 0.0f;
    float diagonal_reach = 0.0f;
    for (int deg = 0; deg < 360; ++deg) {
      const float a = static_cast<float>(deg) * 3.14159265f / 180.0f;
      const auto out = core.compute(
        Vec2{1.0e6f * std::cos(a), 1.0e6f * std::sin(a)}, Vec2{0.0f, 0.0f});
      worst_belt = std::max(worst_belt, std::max(std::fabs(out.v_a), std::fabs(out.v_b)));
      const float mag = std::sqrt(out.vx * out.vx + out.vy * out.vy);
      if (deg == 0) {
        axial_reach = mag;
      }
      if (deg == 45) {
        diagonal_reach = mag;
      }
    }
    expect_close("sweep: worst belt speed is within the limit", worst_belt, 10.0f, 1e-3f);
    expect_true("sweep: no belt over the limit", worst_belt <= 10.0f + 1e-3f);
    expect_close("sweep: axial reach is 10", axial_reach, 10.0f);
    expect_close("sweep: diagonal reach is 7.071", diagonal_reach, 7.071f);
  }

  std::printf("\n%s (%d failure%s)\n", failures == 0 ? "PASS" : "FAIL", failures,
    failures == 1 ? "" : "s");
  return failures == 0 ? 0 : 1;
}
