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

android {
    namespace = "com.raineworks.tvbridge"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.raineworks.tvbridge"
        minSdk = 26
        targetSdk = 35
        versionCode = versionParts[0] * 10000 + versionParts[1] * 100 + versionParts[2]
        versionName = integrationVersion
    }

    signingConfigs {
        // Sideloaded builds (installed by the integration over ADB, or by
        // hand) are signed with this development key, kept in the repo so
        // every build can update the last. Play Store builds are signed by
        // Google Play; uninstall a sideloaded build before installing one.
        create("sideload") {
            storeFile = file("sideload.jks")
            storePassword = "tvbridge"
            keyAlias = "sideload"
            keyPassword = "tvbridge"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("sideload")
        }
        debug {
            signingConfig = signingConfigs.getByName("sideload")
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

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
