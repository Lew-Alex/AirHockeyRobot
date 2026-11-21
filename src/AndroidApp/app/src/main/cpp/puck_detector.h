#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace fastcam {

struct Hit {
    double x;
    double y;
    double radius;
    double circularity;
};

/** Connected-component detector for a packed binary mask.
 *
 * Each pixel is read from data[y * row_stride + x * pixel_stride]. Rows in the
 * input are GL bottom-up; returned y coordinates use a top-left origin.
 * The object owns its work buffers, so detect() does not allocate per frame.
 */
class PuckDetector {
public:
    PuckDetector(int width, int height);

    // Returns true and writes out when a component passes the detector gates.
    // Throws std::invalid_argument for invalid strides or insufficient capacity.
    bool detect(const std::uint8_t* data,
                std::size_t capacity,
                int row_stride,
                int pixel_stride,
                std::int64_t timestamp_ns,
                Hit& out);

private:
    int width_;
    int height_;
    std::size_t pixel_count_;
    std::vector<std::uint8_t> visited_;
    std::vector<int> queue_;
    bool has_previous_ = false;
    Hit previous_{};
    std::int64_t previous_ns_ = 0;
    std::int64_t last_frame_ns_ = 0;
    double vx_ = 0.0;
    double vy_ = 0.0;
};

}  // namespace fastcam
