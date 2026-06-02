"""Android Builder — Kotlin + Jetpack Compose scaffold."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Optional

from builders.common.logging_util import log_builder
from builders.common.types import BuildResult


class AndroidBuilder:
    name = "Android"
    project_type = "ANDROID"

    def __init__(self, socketio: Any = None):
        self.socketio = socketio

    def build(self, description: str, output_dir: Optional[str] = None) -> BuildResult:
        log_builder(f"Android/Compose build: {description[:80]}", "info", self.socketio)
        out = self._resolve_output(description, output_dir)
        out.mkdir(parents=True, exist_ok=True)
        files: List[str] = []

        pkg = "com.sentinel.app"
        app_name = "SentinelApp"
        if "budget" in description.lower():
            app_name = "BudgetApp"

        files.append(self._write(out / "settings.gradle.kts", 'rootProject.name = "SentinelAndroid"\n'))
        files.append(self._write(out / "build.gradle.kts", _ROOT_GRADLE))
        (out / "app" / "src" / "main" / "java" / "com" / "sentinel" / "app").mkdir(parents=True, exist_ok=True)
        files.append(self._write(out / "app" / "build.gradle.kts", _APP_GRADLE.format(pkg=pkg)))
        files.append(self._write(
            out / "app" / "src" / "main" / "java" / "com" / "sentinel" / "app" / "MainActivity.kt",
            _MAIN_KT.format(app_name=app_name),
        ))
        files.append(self._write(out / "app" / "src" / "main" / "AndroidManifest.xml", _MANIFEST.format(pkg=pkg)))

        launch = f'cd /d "{out}" && gradlew assembleDebug'
        return BuildResult(
            success=True,
            builder=self.name,
            project_type=self.project_type,
            output_dir=str(out),
            entry_point=str(out / "app" / "build.gradle.kts"),
            launch_command=launch,
            files=files,
            build_logs="Android Compose project scaffolded. Build APK with gradlew assembleDebug.",
            artifact_type="app",
        )

    def _resolve_output(self, description: str, output_dir: Optional[str]) -> Path:
        if output_dir:
            return Path(output_dir).expanduser().resolve()
        name = "sentinel_android"
        if "budget" in description.lower():
            name = "budget_app"
        return Path.home() / "Desktop" / name

    def _write(self, path: Path, content: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)


_ROOT_GRADLE = """\
plugins {
    id("com.android.application") version "8.2.0" apply false
    id("org.jetbrains.kotlin.android") version "1.9.20" apply false
}
"""

_APP_GRADLE = """\
plugins {{
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}}
android {{
    namespace = "{pkg}"
    compileSdk = 34
    defaultConfig {{
        applicationId = "{pkg}"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }}
    buildFeatures {{ compose = true }}
    composeOptions {{ kotlinCompilerExtensionVersion = "1.5.4" }}
}}
dependencies {{
    implementation("androidx.activity:activity-compose:1.8.0")
    implementation("androidx.compose.ui:ui:1.5.4")
    implementation("androidx.compose.material3:material3:1.1.2")
}}
"""

_MAIN_KT = """\
package com.sentinel.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {{
    override fun onCreate(savedInstanceState: Bundle?) {{
        super.onCreate(savedInstanceState)
        setContent {{
            MaterialTheme {{
                Surface(modifier = Modifier.fillMaxSize()) {{
                    Text("{app_name} — Sentinel Android Builder", modifier = Modifier.padding(24.dp))
                }}
            }}
        }}
    }}
}}
"""

_MANIFEST = """\
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application android:label="Sentinel" android:supportsRtl="true">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""
