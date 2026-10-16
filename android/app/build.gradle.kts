@file:Suppress("UnstableApiUsage")

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

android {
    namespace = "com.castle.sefirah"

    buildFeatures {
        buildConfig = true
    }


    defaultConfig {
        applicationId = "com.orionmini.mobile"
        manifestPlaceholders["appAuthRedirectScheme"] = "com.orionmini.mobile.hosted"
        minSdk = 26
        buildConfigField("boolean", "HAS_FIREBASE", hasFirebase.toString())
        buildConfigField("boolean", "HAS_FIREBASE_PUSH", hasPush.toString())
        buildConfigField("boolean", "INDEPENDENT", independent.toString())
        manifestPlaceholders["orionFirebaseEnabled"] = hasFirebase.toString()
        manifestPlaceholders["orionFirebasePushEnabled"] = hasPush.toString()

        versionCode = providers.gradleProperty("orionVersionCode").orNull?.toInt()
            ?: ((System.currentTimeMillis() / 60000L) - 26297280L).toInt()
        versionName = "0.9.4"
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
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
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

    buildFeatures {
        compose = true
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
