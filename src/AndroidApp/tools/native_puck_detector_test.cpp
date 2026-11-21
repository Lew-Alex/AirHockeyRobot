#include "puck_detector.h"

#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace {
constexpr int kPixelStride = 4;

void square(std::vector<std::uint8_t>& bytes, int row_stride,
            int x0, int y0, int side) {
    for (int y = y0; y < y0 + side; ++y) {
        for (int x = x0; x < x0 + side; ++x) {
            bytes[static_cast<std::size_t>(y) * row_stride + x * kPixelStride] = 255;
        }
    }
}

bool near(double a, double b, double epsilon = 1e-9) {
    return std::abs(a - b) <= epsilon;
}

void test_largest_component_then_nearest_continuity() {
    constexpr int width = 100;
    constexpr int height = 60;
    constexpr int stride = width * kPixelStride;
    fastcam::PuckDetector detector(width, height);
    fastcam::Hit hit{};
    std::vector<std::uint8_t> frame(stride * height);

    square(frame, stride, 10, 20, 5);
    square(frame, stride, 65, 20, 7);
    assert(detector.detect(frame.data(), frame.size(), stride, kPixelStride,
                           1'000'000'000, hit));
    assert(near(hit.x, 68.0));
    assert(near(hit.y, height - 1 - 23.0));
    assert(near(hit.radius, std::sqrt(49.0 / 3.14159265358979323846)));

    std::fill(frame.begin(), frame.end(), 0);
    square(frame, stride, 20, 20, 5);
    square(frame, stride, 75, 20, 5);
    // Within the continuity window, the closer equal-sized blob wins.
    assert(detector.detect(frame.data(), frame.size(), stride, kPixelStride,
                           1'030'000'000, hit));
    assert(near(hit.x, 77.0));
}

void test_loss_reacquisition_and_timestamp_rules() {
    constexpr int width = 100;
    constexpr int height = 60;
    constexpr int stride = width * kPixelStride;
    fastcam::PuckDetector detector(width, height);
    fastcam::Hit hit{};
    std::vector<std::uint8_t> frame(stride * height);

    square(frame, stride, 10, 10, 5);
    assert(detector.detect(frame.data(), frame.size(), stride, kPixelStride,
                           1'000'000'000, hit));
    const double original_x = hit.x;

    // A larger component outside the short continuity window can reacquire.
    std::fill(frame.begin(), frame.end(), 0);
    square(frame, stride, 70, 10, 7);
    assert(detector.detect(frame.data(), frame.size(), stride, kPixelStride,
                           1'200'000'001, hit));
    assert(hit.x > original_x + 50.0);

    // Duplicate and regressed frame timestamps are ignored, without touching out.
    const double reacquired_x = hit.x;
    std::fill(frame.begin(), frame.end(), 0);
    square(frame, stride, 20, 10, 5);
    assert(!detector.detect(frame.data(), frame.size(), stride, kPixelStride,
                            1'200'000'001, hit));
    assert(near(hit.x, reacquired_x));
    assert(!detector.detect(frame.data(), frame.size(), stride, kPixelStride,
                            1'100'000'000, hit));
    assert(near(hit.x, reacquired_x));

    // A newer empty frame is accepted as a lost detection.
    std::fill(frame.begin(), frame.end(), 0);
    assert(!detector.detect(frame.data(), frame.size(), stride, kPixelStride,
                            1'210'000'000, hit));
    assert(near(hit.x, reacquired_x));
}

void test_padded_odd_width_and_border_orientation() {
    constexpr int width = 65;
    constexpr int height = 40;
    constexpr int stride = width + 3;
    const std::size_t length = static_cast<std::size_t>(stride) * (height - 1) +
                               width;
    std::vector<std::uint8_t> frame(length, 0);
    // Padding bytes are nonzero but must not become mask pixels.
    for (int y = 0; y + 1 < height; ++y) {
        for (int x = width; x < stride; ++x) {
            frame[static_cast<std::size_t>(y) * stride + x] = 255;
        }
    }
    // A 3x3 block at the GL bottom-left edge reports top-left y = height - 2.
    for (int y = 0; y < 3; ++y) {
        for (int x = 0; x < 3; ++x) {
            frame[static_cast<std::size_t>(y) * stride + x] = 255;
        }
    }
    fastcam::PuckDetector detector(width, height);
    fastcam::Hit hit{};
    assert(detector.detect(frame.data(), frame.size(), stride, 1,
                           10, hit));
    assert(near(hit.x, 1.0));
    assert(near(hit.y, height - 2.0));
    assert(near(hit.circularity, 4.0 * 3.14159265358979323846 * 9.0 / 144.0));
}

void test_bad_strides_and_capacity_throw() {
    fastcam::PuckDetector detector(8, 6);
    std::vector<std::uint8_t> frame(8 * 6 * kPixelStride);
    fastcam::Hit hit{};
    const auto must_throw = [&](int row_stride, int pixel_stride,
                                std::size_t capacity) {
        bool threw = false;
        try {
            detector.detect(frame.data(), capacity, row_stride, pixel_stride, 1, hit);
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        assert(threw);
    };
    must_throw(8 * 4 - 1, 4, frame.size());
    must_throw(8 * 4, 0, frame.size());
    must_throw(8 * 4, 5, frame.size());
    must_throw(8 * 4, 4, frame.size() - 1);
}
}  // namespace

int main() {
    test_largest_component_then_nearest_continuity();
    test_loss_reacquisition_and_timestamp_rules();
    test_padded_odd_width_and_border_orientation();
    test_bad_strides_and_capacity_throw();
    return 0;
}
