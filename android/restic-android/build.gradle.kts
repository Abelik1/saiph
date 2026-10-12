plugins { alias(libs.plugins.sefirah.android.library) }
android { namespace = "io.github.resticdroid.restic" }
dependencies {
    implementation(libs.kotlinx.coroutines.core)
    testImplementation(libs.junit)
    testImplementation("org.json:json:20240303")
}
// Executable libraries are produced by scripts/build-android-restic.py, not a
// shared library linker. Never silently publish an APK without either ABI.
tasks.named("preBuild") {
    // Capture serializable File values while configuring the task. Calling the
    // script's file()/layout accessors from doFirst breaks configuration cache.
    val requiredExecutables = listOf("arm64-v8a", "x86_64").map { abi ->
        layout.projectDirectory.file("src/main/jniLibs/$abi/librestic.so").asFile
    }
    inputs.files(requiredExecutables).withPropertyName("bundledResticExecutables")
    doFirst {
        requiredExecutables.forEach { executable ->
            check(executable.isFile) {
                "Build pinned Android restic first: scripts/build-android-restic.py"
            }
        }
    }
}
