#include "puck_detector.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace fastcam {
namespace {
constexpr double kPi = 3.141592653589793238462643383279502884;
}

PuckDetector::PuckDetector(int width, int height)
    : width_(width), height_(height), pixel_count_(0) {
    if (width <= 0 || height <= 0) {
        throw std::invalid_argument("width and height must be positive");
    }
    const auto pixels = static_cast<std::uint64_t>(width) *
                        static_cast<std::uint64_t>(height);
    // Queue entries and component sizes mirror the Kotlin IntArray indexing.
    if (pixels > static_cast<std::uint64_t>(std::numeric_limits<int>::max())) {
        throw std::invalid_argument("image is too large");
    }
    pixel_count_ = static_cast<std::size_t>(pixels);
    visited_.resize(pixel_count_);
    queue_.resize(pixel_count_);
}

bool PuckDetector::detect(const std::uint8_t* data,
                          std::size_t capacity,
                          int row_stride,
                          int pixel_stride,
                          std::int64_t timestamp_ns,
                          Hit& out) {
    if (pixel_stride < 1 || pixel_stride > 4 || row_stride < 0 ||
        static_cast<std::int64_t>(row_stride) <
            static_cast<std::int64_t>(width_) * pixel_stride) {
        throw std::invalid_argument("invalid pixel or row stride");
    }
    const std::uint64_t length =
        static_cast<std::uint64_t>(row_stride) * (height_ - 1) +
        static_cast<std::uint64_t>(width_) * pixel_stride;
    // Kotlin's backing read buffer is width * height * 4 bytes.
    if (length > static_cast<std::uint64_t>(pixel_count_) * 4 ||
        length > capacity || (length != 0 && data == nullptr)) {
        throw std::invalid_argument("input buffer is too small");
    }

    if (timestamp_ns <= last_frame_ns_) return false;
    last_frame_ns_ = timestamp_ns;

    std::fill(visited_.begin(), visited_.end(), static_cast<std::uint8_t>(0));

    // Accepted timestamps are positive and increasing, so this difference cannot
    // overflow. Match Kotlin's integer subtraction followed by double division.
    const double elapsed = static_cast<double>(timestamp_ns - previous_ns_) / 1.0e9;
    const bool use_previous = has_previous_ && elapsed >= 0.0 && elapsed <= 0.15;
    const double predicted_x = (use_previous ? previous_.x : 0.0) + vx_ * elapsed;
    const double predicted_y = (use_previous ? previous_.y : 0.0) + vy_ * elapsed;
    const double diagonal = std::hypot(static_cast<double>(width_),
                                       static_cast<double>(height_));
    const double gate = diagonal * std::min(1.0, 0.12 + 5.0 * elapsed);

    bool found = false;
    Hit best{};
    double best_score = -std::numeric_limits<double>::infinity();

    for (std::size_t seed = 0; seed < pixel_count_; ++seed) {
        if (visited_[seed] != 0) continue;
        const std::size_t seed_y = seed / static_cast<std::size_t>(width_);
        const std::size_t seed_x = seed - seed_y * static_cast<std::size_t>(width_);
        if (data[seed_y * static_cast<std::size_t>(row_stride) +
                 seed_x * static_cast<std::size_t>(pixel_stride)] == 0) {
            continue;
        }

        std::size_t head = 0;
        std::size_t tail = 1;
        queue_[0] = static_cast<int>(seed);
        visited_[seed] = 1;
        double sum_x = 0.0;
        double sum_y = 0.0;
        std::int64_t perimeter = 0;

        while (head < tail) {
            const int index = queue_[head++];
            const int x = index % width_;
            const int y = index / width_;
            sum_x += x;
            sum_y += height_ - 1 - y;

            const auto visit = [&](int nx, int ny, bool valid) {
                if (!valid) {
                    ++perimeter;
                    return;
                }
                const std::size_t neighbor =
                    static_cast<std::size_t>(ny) * static_cast<std::size_t>(width_) +
                    static_cast<std::size_t>(nx);
                if (data[static_cast<std::size_t>(ny) *
                             static_cast<std::size_t>(row_stride) +
                         static_cast<std::size_t>(nx) *
                             static_cast<std::size_t>(pixel_stride)] == 0) {
                    ++perimeter;
                } else if (visited_[neighbor] == 0) {
                    visited_[neighbor] = 1;
                    queue_[tail++] = static_cast<int>(neighbor);
                }
            };

            visit(x - 1, y, x > 0);
            visit(x + 1, y, x + 1 < width_);
            visit(x, y - 1, y > 0);
            visit(x, y + 1, y + 1 < height_);
        }

        if (tail < 3 || static_cast<double>(tail) > pixel_count_ * 0.025 ||
            perimeter == 0) {
            continue;
        }
        const double circularity =
            4.0 * kPi * static_cast<double>(tail) /
            (static_cast<double>(perimeter) * static_cast<double>(perimeter));
        if (circularity < 0.22) continue;

        const Hit hit{sum_x / static_cast<double>(tail),
                      sum_y / static_cast<double>(tail),
                      std::sqrt(static_cast<double>(tail) / kPi), circularity};
        const double distance = std::hypot(hit.x - predicted_x,
                                           hit.y - predicted_y);
        if (use_previous && distance > gate) continue;
        const double score = use_previous ? -distance
                                          : static_cast<double>(tail) * circularity;
        if (score > best_score) {
            best = hit;
            best_score = score;
            found = true;
        }
    }

    if (!found) return false;

    if (use_previous && elapsed > 0.0) {
        vx_ = (best.x - previous_.x) / elapsed;
        vy_ = (best.y - previous_.y) / elapsed;
    } else {
        vx_ = 0.0;
        vy_ = 0.0;
    }
    previous_ = best;
    previous_ns_ = timestamp_ns;
    has_previous_ = true;
    out = best;
    return true;
}

}  // namespace fastcam
