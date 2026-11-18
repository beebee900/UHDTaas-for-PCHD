plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "local.atra.atra_mobile"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "local.atra.mobile"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    // One app per audience (design 08, WP01): flutter build apk --flavor ward -t lib/main_ward.dart
    flavorDimensions += "audience"
    productFlavors {
        create("person") { dimension = "audience"; applicationIdSuffix = ".person" }
        create("carer") { dimension = "audience"; applicationIdSuffix = ".carer" }
        create("patient") { dimension = "audience"; applicationIdSuffix = ".patient" }
        create("ward") { dimension = "audience"; applicationIdSuffix = ".ward" }
        create("chw") { dimension = "audience"; applicationIdSuffix = ".chw" }
    }

    buildTypes {
        release {
            // Demo builds are signed with the debug key; a store release needs its own key.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
