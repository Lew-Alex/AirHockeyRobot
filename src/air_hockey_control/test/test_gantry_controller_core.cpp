#include <gtest/gtest.h>

#include <cmath>

#include "air_hockey_control/gantry_controller_core.hpp"

namespace air_hockey_control
{
namespace
{

constexpr float kMaxVAxis = 10.0f;

GantryLimits make_limits()
{
  return GantryLimits{kMaxVAxis, diagonal_limit_for(kMaxVAxis)};
}

TEST(GantryControllerCore, proportional_term_and_belt_mapping)
{
  GantryControllerCore core(4.0f, make_limits());
  const auto out = core.compute(Vec2{0.5f, 0.5f}, Vec2{0.0f, 0.0f});

  EXPECT_NEAR(out.vx, 2.0f, 1e-3f);
  EXPECT_NEAR(out.vy, 2.0f, 1e-3f);
  EXPECT_NEAR(out.v_a, 4.0f, 1e-3f);
  EXPECT_NEAR(out.v_b, 0.0f, 1e-3f);
}

TEST(GantryControllerCore, axis_speed_reaches_the_belt_limit)
{
  GantryControllerCore core(4.0f, make_limits());
  const auto out = core.compute(Vec2{5.0f, 0.0f}, Vec2{0.0f, 0.0f});

  EXPECT_NEAR(out.vx, kMaxVAxis, 1e-3f);
  EXPECT_NEAR(out.vy, 0.0f, 1e-3f);
  EXPECT_NEAR(out.v_a, kMaxVAxis, 1e-3f);
  EXPECT_NEAR(out.v_b, kMaxVAxis, 1e-3f);
}

TEST(GantryControllerCore, diagonal_reach_is_the_axis_limit_over_root_two)
{
  GantryControllerCore core(4.0f, make_limits());
  const auto out = core.compute(Vec2{2.0f, 2.0f}, Vec2{0.0f, 0.0f});

  EXPECT_NEAR(out.vx, 5.0f, 1e-3f);
  EXPECT_NEAR(out.vy, 5.0f, 1e-3f);
  EXPECT_NEAR(std::sqrt(out.vx * out.vx + out.vy * out.vy), diagonal_limit_for(kMaxVAxis), 1e-3f);
  EXPECT_NEAR(out.v_a, kMaxVAxis, 1e-3f);
  EXPECT_NEAR(out.v_b, 0.0f, 1e-3f);
}

TEST(GantryControllerCore, direction_is_preserved_through_the_scaling)
{
  GantryControllerCore core(4.0f, make_limits());
  const auto out = core.compute(Vec2{-2.0f, 2.0f}, Vec2{0.0f, 0.0f});

  EXPECT_NEAR(out.vx, -5.0f, 1e-3f);
  EXPECT_NEAR(out.vy, 5.0f, 1e-3f);
  EXPECT_NEAR(out.v_a, 0.0f, 1e-3f);
  EXPECT_NEAR(out.v_b, -kMaxVAxis, 1e-3f);
}

TEST(GantryControllerCore, zero_error_is_zero_velocity)
{
  GantryControllerCore core(4.0f, make_limits());
  const auto out = core.compute(Vec2{0.3f, -0.2f}, Vec2{0.3f, -0.2f});

  EXPECT_NEAR(out.vx, 0.0f, 1e-6f);
  EXPECT_NEAR(out.vy, 0.0f, 1e-6f);
}

TEST(GantryControllerCore, no_direction_can_exceed_the_belt_limit)
{
  GantryControllerCore core(4.0f, make_limits());
  for (int deg = 0; deg < 360; ++deg) {
    const float a = static_cast<float>(deg) * 3.14159265f / 180.0f;
    const auto out = core.compute(Vec2{1.0e6f * std::cos(a), 1.0e6f * std::sin(a)}, Vec2{0.0f, 0.0f});
    EXPECT_LE(std::fabs(out.v_a), kMaxVAxis + 1e-3f) << "at " << deg << " degrees";
    EXPECT_LE(std::fabs(out.v_b), kMaxVAxis + 1e-3f) << "at " << deg << " degrees";
  }
}

}  // namespace
}  // namespace air_hockey_control
