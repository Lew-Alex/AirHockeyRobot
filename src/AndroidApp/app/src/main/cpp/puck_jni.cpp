#include "puck_detector.h"
#include <jni.h>
#include <cstdint>
#include <new>
#include <stdexcept>

namespace {
void fail(JNIEnv* env, const char* type, const char* message) {
    if (auto cls = env->FindClass(type)) env->ThrowNew(cls, message);
}
fastcam::PuckDetector* detector(jlong handle) {
    return reinterpret_cast<fastcam::PuckDetector*>(static_cast<std::intptr_t>(handle));
}
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_example_fastcam_PuckNativeBindings_create(JNIEnv* env, jobject, jint width, jint height) {
    try {
        auto* value = new fastcam::PuckDetector(width, height);
        return static_cast<jlong>(reinterpret_cast<std::intptr_t>(value));
    } catch (const std::bad_alloc&) {
        fail(env, "java/lang/OutOfMemoryError", "Allocating native puck detector");
    } catch (const std::exception& error) {
        fail(env, "java/lang/IllegalArgumentException", error.what());
    }
    return 0;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_example_fastcam_PuckNativeBindings_detect(JNIEnv* env, jobject, jlong handle, jobject mask,
    jint row_stride, jint pixel_stride, jlong timestamp_ns, jdoubleArray output) {
    auto* value = detector(handle);
    if (!value || !mask || !output) {
        fail(env, "java/lang/IllegalArgumentException", "Missing native handle, mask or result buffer");
        return JNI_FALSE;
    }
    auto* data = static_cast<const std::uint8_t*>(env->GetDirectBufferAddress(mask));
    auto capacity = env->GetDirectBufferCapacity(mask);
    if (!data || capacity < 0 || env->GetArrayLength(output) < 4) {
        fail(env, "java/lang/IllegalArgumentException", "Invalid native handle, direct mask or result buffer");
        return JNI_FALSE;
    }
    try {
        fastcam::Hit hit{};
        if (!value->detect(data, static_cast<std::size_t>(capacity), row_stride, pixel_stride, timestamp_ns, hit))
            return JNI_FALSE;
        const jdouble result[] = {hit.x, hit.y, hit.radius, hit.circularity};
        env->SetDoubleArrayRegion(output, 0, 4, result);
        return env->ExceptionCheck() ? JNI_FALSE : JNI_TRUE;
    } catch (const std::bad_alloc&) {
        fail(env, "java/lang/OutOfMemoryError", "Native puck detection");
    } catch (const std::exception& error) {
        fail(env, "java/lang/IllegalArgumentException", error.what());
    }
    return JNI_FALSE;
}

extern "C" JNIEXPORT void JNICALL
Java_com_example_fastcam_PuckNativeBindings_destroy(JNIEnv*, jobject, jlong handle) {
    delete detector(handle);
}
