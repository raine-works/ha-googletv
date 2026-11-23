plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// The version comes from the integration's manifest, so both release together
val integrationVersion: String = run {
    val manifest = rootProject.file("../custom_components/googletv/manifest.json").readText()
    Regex("\"version\"\\s*:\\s*\"([^\"]+)\"").find(manifest)?.groupValues?.get(1) ?: "0.0.0"
}
val versionParts = integrationVersion.split(".").map { it.toIntOrNull() ?: 0 } + listOf(0, 0, 0)

// The commit it's built from, shown on the app's screen and reported to Home Assistant
val gitSha: String = try {
    providers.exec { commandLine("git", "rev-parse", "--short=7", "HEAD") }
        .standardOutput.asText.get().trim().ifEmpty { "dev" }
} catch (e: Exception) {
    "dev"
}

android {
    namespace = "com.raineworks.tvbridge"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.raineworks.tvbridge"
        minSdk = 26
        targetSdk = 36
        versionCode = versionParts[0] * 10000 + versionParts[1] * 100 + versionParts[2]
        versionName = integrationVersion
        buildConfigField("String", "GIT_SHA", "\"$gitSha\"")
        // TVs are ARM: WebRTC's native code for those only (on anything else
        // a camera falls back to HLS)
        ndk { abiFilters += listOf("armeabi-v7a", "arm64-v8a") }
    }

    // Release builds are signed with the project's private release key when
    // CI provides it: its keystore and passwords come from the environment
    // (RELEASE_KEYSTORE is the decoded file's path), never from the repo.
    // Without it (a developer's machine, a pull request's build) the build is
    // signed with Android's debug key, which is enough to run and test it. The
    // integration installs the app over ADB; a TV that has the app signed with
    // another key has it uninstalled first (see the integration's adb.py).
    val releaseKeystore = System.getenv("RELEASE_KEYSTORE")?.takeIf { it.isNotEmpty() }

    if (releaseKeystore != null) {
        signingConfigs.create("release") {
            storeFile = file(releaseKeystore)
            // GitHub Actions passes a secret that isn't set as an empty string, so empty counts as unset
            fun env(name: String) = System.getenv(name)?.takeIf { it.isNotEmpty() }
            storePassword = env("RELEASE_KEYSTORE_PASSWORD")
            keyAlias = env("RELEASE_KEY_ALIAS") ?: "upload"
            keyPassword = env("RELEASE_KEY_PASSWORD") ?: env("RELEASE_KEYSTORE_PASSWORD")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName(if (releaseKeystore != null) "release" else "debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        buildConfig = true
    }
    lint {
        abortOnError = true
        checkReleaseBuilds = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.media3:media3-exoplayer:1.5.1")
    implementation("androidx.media3:media3-exoplayer-hls:1.5.1")
    implementation("androidx.media3:media3-exoplayer-rtsp:1.5.1")
    implementation("androidx.media3:media3-ui:1.5.1")
    implementation("androidx.media3:media3-session:1.5.1")
    // Dashboards: their settings set before the page reads them
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("org.nanohttpd:nanohttpd:2.3.1")
    // The setup screen's QR code
    implementation("com.google.zxing:core:3.5.3")
    // Cameras live over WebRTC, signalled on Home Assistant's websocket
    implementation("io.getstream:stream-webrtc-android:1.3.10")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
