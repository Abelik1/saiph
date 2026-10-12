plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.rikka.refine)
}

android {
    namespace = "sefirah.worker"
    compileSdk = 37

    defaultConfig {
        // app_process payload — only started on API 29+. Host app stays at 23 via overrideLibrary.
        minSdk = 29
        buildConfigField("int", "VERSION_CODE", "2")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        aidl = true
        buildConfig = true
    }

    lint {
        abortOnError = false
    }
}

dependencies {
    compileOnly(libs.androidx.annotation)
    implementation(libs.hidden.compat) {
        exclude(group = "androidx.core", module = "core")
        exclude(group = "androidx.core", module = "core-ktx")
        exclude(group = "dev.rikka.rikkax.buildcompat", module = "buildcompat")
    }
    compileOnly(libs.hidden.stub)
}
