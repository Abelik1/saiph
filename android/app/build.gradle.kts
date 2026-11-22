@file:Suppress("UnstableApiUsage")

import java.net.URI

plugins {
    alias(libs.plugins.sefirah.android.application)
    alias(libs.plugins.compose.compiler)
}

// Hub independence and optional Firebase tester updates are separate choices.
val firebaseOption = providers.gradleProperty("orionFirebase").orNull ?: "false"
require(firebaseOption == null || firebaseOption in listOf("true", "false")) { "orionFirebase must be true or false" }
val independentOption = providers.gradleProperty("orionIndependent").orNull ?: "true"
require(independentOption == null || independentOption in listOf("true", "false")) { "orionIndependent must be true or false" }
val independent = independentOption == "true"
require(!independent || firebaseOption != null) { "Independent builds must explicitly choose Firebase tester updates" }
val hasFirebase = firebaseOption != "false" && file("google-services.json").exists()
require(firebaseOption != "true" || hasFirebase) { "Firebase-enabled builds require private local configuration" }
if (hasFirebase) apply(plugin = "com.google.gms.google-services")
// FCM push is a third, explicit choice. Independent builds default to no push: a
// tester's Hub cannot send FCM through the publisher's Firebase project, so no
// FCM token is created or uploaded. Firebase App Distribution is unaffected.
val pushOption = providers.gradleProperty("orionPush").orNull
require(pushOption == null || pushOption in listOf("true", "false")) { "orionPush must be true or false" }
val hasPush = hasFirebase && (pushOption ?: (!independent).toString()) == "true"
require(pushOption != "true" || hasFirebase) { "orionPush=true requires a Firebase-enabled build" }
// Optional beta signing key, supplied only through the environment, never committed.
val betaKeystore = providers.environmentVariable("SAIPH_ANDROID_KEYSTORE").orNull
// Public account origin, supplied by the distributor; independent builds leave automatic trials off.
val accountOrigin = providers.gradleProperty("orionAccountOrigin").orNull ?: ""
require(accountOrigin.isEmpty() || runCatching {
    val uri = URI(accountOrigin)
    uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.rawUserInfo == null &&
        uri.port == -1 && uri.rawPath.isNullOrEmpty() && uri.rawQuery == null && uri.rawFragment == null
}.getOrDefault(false)) { "orionAccountOrigin must be a canonical HTTPS origin" }

android {
    namespace = "com.castle.sefirah"

    buildFeatures {
        buildConfig = true
    }


    defaultConfig {
        applicationId = "com.orionmini.mobile"
        manifestPlaceholders["appAuthRedirectScheme"] = "com.orionmini.mobile.hosted"
        manifestPlaceholders["authRedirectPath"] = "/android/oauth2redirect"
        buildConfigField("String", "AUTH_REDIRECT", "\"https://usesaiph.com/android/oauth2redirect\"")
        minSdk = 26
        // The bundled restic runtime is built and checked for these two ABIs.
        // Do not advertise 32-bit installs whose nativeLibraryDir lacks restic.
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
        buildConfigField("boolean", "HAS_FIREBASE", hasFirebase.toString())
        buildConfigField("boolean", "HAS_FIREBASE_PUSH", hasPush.toString())
        buildConfigField("boolean", "INDEPENDENT", independent.toString())
        buildConfigField("String", "ACCOUNT_ORIGIN", "\"$accountOrigin\"")
        manifestPlaceholders["orionFirebaseEnabled"] = hasFirebase.toString()
        manifestPlaceholders["orionFirebasePushEnabled"] = hasPush.toString()

        versionCode = providers.gradleProperty("orionVersionCode").orNull?.toInt()
            ?: ((System.currentTimeMillis() / 60000L) - 26297280L).toInt()
        versionName = "0.9.9"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        externalNativeBuild {
            cmake {
                arguments += listOf("-DANDROID_STL=none")
            }
        }
    }

    dependenciesInfo {
        includeInApk = false
        includeInBundle = false
    }

    signingConfigs {
        if (betaKeystore != null) create("beta") {
            storeFile = file(betaKeystore)
            storePassword = providers.environmentVariable("SAIPH_ANDROID_KEYSTORE_PASSWORD").orNull
            keyAlias = providers.environmentVariable("SAIPH_ANDROID_KEY_ALIAS").orNull
            keyPassword = providers.environmentVariable("SAIPH_ANDROID_KEY_PASSWORD").orNull
        }
    }

    buildTypes {
        // Only debug and beta carry the full App Distribution SDK (in-app tester updates).
        debug {
            buildConfigField("boolean", "HAS_APP_DISTRIBUTION", hasFirebase.toString())
        }
        // Store and website releases: the same code as beta, signed with the owner's release key
        // from the environment (docs/ANDROID_DISTRIBUTION.md). R8 stays off until it is accepted on devices.
        release {
            isMinifyEnabled = false
            isShrinkResources = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("beta")
            buildConfigField("boolean", "HAS_APP_DISTRIBUTION", "false")
        }
        // Outside beta testers: not debuggable, same code as debug (R8 minification is
        // not yet accepted on devices), signed only when SAIPH_ANDROID_KEYSTORE is set.
        create("beta") {
            isDebuggable = false
            isJniDebuggable = false
            isMinifyEnabled = false
            isShrinkResources = false
            matchingFallbacks += listOf("release")
            signingConfig = signingConfigs.findByName("beta")
            buildConfigField("boolean", "HAS_APP_DISTRIBUTION", hasFirebase.toString())
        }
    }
    // Public deployment defaults are placed here by the distributor, never committed.
    sourceSets.getByName("release").assets.directories.add("src/beta/assets")

    // Two apps (docs/ANDROID_DISTRIBUTION.md): "Saiph" on Google Play and "Saiph Unlocked" from
    // usesaiph.com. Separate app IDs and sign-in callbacks, so one phone can have both.
    flavorDimensions += "store"
    productFlavors {
        // Downloaded from usesaiph.com: every feature, and Saiph installs its own updates.
        create("direct") {
            dimension = "store"
            applicationIdSuffix = ".unlocked"
            resValue("string", "app_name", "Saiph Unlocked")
            manifestPlaceholders["appAuthRedirectScheme"] = "com.orionmini.mobile.unlocked.hosted"
            manifestPlaceholders["authRedirectPath"] = "/android/unlocked/oauth2redirect"
            buildConfigField("String", "AUTH_REDIRECT", "\"https://usesaiph.com/android/unlocked/oauth2redirect\"")
            buildConfigField("boolean", "PLAY_STORE", "false")
        }
        // Google Play: within Play's permission policies (src/play/AndroidManifest.xml); Play installs updates.
        create("play") {
            dimension = "store"
            buildConfigField("boolean", "PLAY_STORE", "true")
        }
    }

    buildFeatures {
        compose = true
        resValues = true  // The direct flavor names itself Saiph Unlocked.
    }

    packaging {
        resources {
            // Bouncy Castle 1.85 ships the same license path in three modules.
            // Retain all notice text while avoiding a duplicate-resource failure.
            merges += "META-INF/LICENSE.md"
            excludes += "/META-INF/{AL2.0,LGPL2.1,DEPENDENCIES}"
            excludes += "META-INF/versions/**"
        }
        jniLibs {
            useLegacyPackaging = true
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/jni/CMakeLists.txt")
        }
    }
}

// Beta builds are direct downloads for testers; Play has its own testing tracks.
androidComponents {
    beforeVariants { variant ->
        if (variant.buildType == "beta" && variant.productFlavors.contains("store" to "play")) variant.enable = false
    }
}

kotlin {
    compilerOptions {
        freeCompilerArgs.addAll(
            "-opt-in=androidx.compose.animation.ExperimentalAnimationApi",
            "-opt-in=androidx.compose.animation.graphics.ExperimentalAnimationGraphicsApi",
            "-opt-in=androidx.compose.foundation.ExperimentalFoundationApi",
            "-opt-in=androidx.compose.foundation.layout.ExperimentalLayoutApi",
            "-opt-in=androidx.compose.material3.ExperimentalMaterial3Api",
            "-opt-in=androidx.compose.ui.ExperimentalComposeUiApi",
            "-opt-in=kotlinx.coroutines.FlowPreview",
        )
    }
}

dependencies {
    implementation("net.openid:appauth:0.11.1")
    implementation("com.google.crypto.tink:tink-android:1.23.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation(libs.kotlinx.serialization.json)
    implementation(platform("com.google.firebase:firebase-bom:34.19.0"))
    implementation("com.google.firebase:firebase-messaging")
    implementation("com.google.firebase:firebase-appdistribution-api:16.0.0-beta20")
    // Full self-update SDK: pre-release build types only, never a Play-bound release.
    debugImplementation("com.google.firebase:firebase-appdistribution:16.0.0-beta20")
    "betaImplementation"("com.google.firebase:firebase-appdistribution:16.0.0-beta20")
    api(projects.core.common)
    api(projects.core.network)
    implementation(project(":restic-android"))
    api(projects.core.presentation)
    api(projects.data)
    api(projects.domain)

    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.hilt.navigation.compose)
    implementation(libs.core.ktx)
    implementation(libs.androidx.work)
    implementation(libs.lifecycle.runtime.ktx)
    implementation(platform(libs.compose.bom))
    implementation(libs.bundles.compose.android)
    implementation(libs.material3.adaptive.navigation.suite)
    implementation(libs.coil.compose)
    implementation(libs.compose.navigation)
    implementation(libs.splashscreen)

    implementation(libs.richtext.m3)
    implementation(libs.richtext.commonmark)
    implementation(libs.reorderable)

    implementation(libs.androidx.media)
    implementation(libs.androidx.hilt.work)
    implementation(libs.zxing.cpp.android)
    implementation(libs.camerax.core)
    implementation(libs.camerax.camera2)
    implementation(libs.camerax.lifecycle)
    implementation(libs.camerax.view)
    implementation(libs.guava)

    compileOnly(libs.hidden.stub)

    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation("androidx.work:work-testing:2.10.0")
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.compose.bom))
    androidTestImplementation(libs.compose.ui.test.junit)
    debugImplementation(libs.compose.ui.tooling)
    debugImplementation(libs.compose.ui.test.manifest)
}
