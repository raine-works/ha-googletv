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
    }

    // A Google Play build (`./gradlew bundleRelease -Pplay`) is signed with the
    // private upload key (never the sideload key in this repo): its keystore
    // and passwords come from the environment, as CI's secrets give them.
    // Google Play re-signs it with the app's own key (Play App Signing), so a
    // Play install and a sideloaded one can't update each other.
    val play = providers.gradleProperty("play").isPresent

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

    if (play) {
        signingConfigs.create("upload") {
            storeFile = file(System.getenv("UPLOAD_KEYSTORE") ?: error("UPLOAD_KEYSTORE isn't set"))
            storePassword = System.getenv("UPLOAD_KEYSTORE_PASSWORD")
            keyAlias = System.getenv("UPLOAD_KEY_ALIAS") ?: "upload"
            keyPassword = System.getenv("UPLOAD_KEY_PASSWORD") ?: System.getenv("UPLOAD_KEYSTORE_PASSWORD")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName(if (play) "upload" else "sideload")
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
