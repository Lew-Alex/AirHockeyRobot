plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.example.fastcam"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.example.fastcam"
        minSdk = 31
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // GPU-backed MP4 burn-in happens after capture, leaving high-speed camera outputs intact.
    implementation("androidx.media3:media3-transformer:1.5.1")
    implementation("androidx.media3:media3-effect:1.5.1")
}

// Use the same Python tracker as the desktop perception test, without copying it.
chaquopy {
    defaultConfig {
        version = "3.10"
        // Override Python discovery when needed: -PtrackingPython=C:/path/to/python.exe
        providers.gradleProperty("trackingPython").orNull?.let { buildPython(it) }
        pip {
            install("numpy==1.26.2")
            install("opencv-python==4.5.1.48")
        }
    }
    sourceSets {
        getByName("main") {
            srcDir("../../perception/androidAppPerceptionTesting")
            include("puck_tracker.py", "android_bridge.py")
        }
    }
}
