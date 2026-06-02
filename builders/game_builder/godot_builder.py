"""Game Builder — Godot 4 project scaffolds (2D / Flappy-style games)."""
from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Any, List, Optional

from builders.common.logging_util import log_builder
from builders.common.types import BuildResult


class GameBuilder:
    name = "Godot"
    project_type = "GAME"

    def __init__(self, socketio: Any = None):
        self.socketio = socketio

    def build(self, description: str, output_dir: Optional[str] = None) -> BuildResult:
        log_builder(f"Game/Godot build: {description[:80]}", "info", self.socketio)
        out = self._resolve_output(description, output_dir)
        out.mkdir(parents=True, exist_ok=True)
        files: List[str] = []

        is_flappy = bool(re.search(r"flappy|bird", description, re.I))
        project_name = "FlappySentinel" if is_flappy else "SentinelGame"

        files.append(self._write(out / "project.godot", _PROJECT_GODOT.format(name=project_name)))
        (out / "scenes").mkdir(exist_ok=True)
        (out / "scripts").mkdir(exist_ok=True)
        (out / "assets").mkdir(exist_ok=True)
        files.append(self._write(out / "scenes" / "main.tscn", _MAIN_SCENE))
        files.append(self._write(out / "scripts" / "game.gd", _GAME_SCRIPT_FLAPPY if is_flappy else _GAME_SCRIPT_GENERIC))
        files.append(self._write(out / "scripts" / "player.gd", _PLAYER_SCRIPT))
        files.append(self._write(out / "scripts" / "pipe.gd", _PIPE_SCRIPT))
        files.append(self._write(out / "export_presets.cfg", _EXPORT_CFG))

        entry = str(out / "project.godot")
        godot_bin = self._find_godot()
        launch = f'"{godot_bin}" --path "{out}"' if godot_bin else f'godot --path "{out}"'

        return BuildResult(
            success=True,
            builder=self.name,
            project_type=self.project_type,
            output_dir=str(out),
            entry_point=entry,
            launch_command=launch,
            files=files,
            build_logs=f"Godot project created ({len(files)} files). Open in Godot Editor or run launch command.",
            artifact_type="game",
        )

    def _resolve_output(self, description: str, output_dir: Optional[str]) -> Path:
        if output_dir:
            return Path(output_dir).expanduser().resolve()
        name = "flappy_bird" if re.search(r"flappy|bird", description, re.I) else "sentinel_game"
        name = re.sub(r"[^a-z0-9_]", "", name.lower())[:30]
        return Path.home() / "Desktop" / name

    def _write(self, path: Path, content: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)

    def _find_godot(self) -> Optional[str]:
        import shutil
        for c in ("godot", "godot.exe"):
            f = shutil.which(c)
            if f:
                return f
        for p in (r"C:\Program Files\Godot\Godot.exe", r"C:\Tools\Godot.exe"):
            if Path(p).is_file():
                return p
        return None


_PROJECT_GODOT = """\
; SentinelAI Game Builder — Godot 4
config_version=5

[application]
config/name="{name}"
run/main_scene="res://scenes/main.tscn"
config/features=PackedStringArray("4.2", "Forward Plus")

[display]
window/size/viewport_width=480
window/size/viewport_height=720
"""

_MAIN_SCENE = """\
[gd_scene load_steps=4 format=3 uid="uid://sentinel_main"]

[ext_resource type="Script" path="res://scripts/game.gd" id="1"]
[ext_resource type="Script" path="res://scripts/player.gd" id="2"]

[sub_resource type="RectangleShape2D" id="RectangleShape2D_player"]
size = Vector2(40, 40)

[node name="Main" type="Node2D"]
script = ExtResource("1")

[node name="Player" type="CharacterBody2D" parent="."]
position = Vector2(120, 360)
script = ExtResource("2")

[node name="CollisionShape2D" type="CollisionShape2D" parent="Player"]
shape = SubResource("RectangleShape2D_player")

[node name="Camera2D" type="Camera2D" parent="."]
position = Vector2(240, 360)

[node name="UI" type="CanvasLayer" parent="."]

[node name="ScoreLabel" type="Label" parent="UI"]
offset_left = 180.0
offset_top = 40.0
offset_right = 300.0
offset_bottom = 80.0
theme_override_font_sizes/font_size = 32
text = "0"
horizontal_alignment = 1
"""

_GAME_SCRIPT_FLAPPY = textwrap.dedent("""\
extends Node2D

@onready var player = $Player
@onready var score_label = $UI/ScoreLabel

var score := 0
var pipe_scene = preload("res://scripts/pipe.gd")
var spawn_timer := 0.0

func _ready() -> void:
    score_label.text = "0"

func _process(delta: float) -> void:
    spawn_timer += delta
    if spawn_timer > 1.8:
        spawn_timer = 0.0
        _spawn_pipe()

func _spawn_pipe() -> void:
    var gap_y = randf_range(180.0, 520.0)
    var top = ColorRect.new()
    top.color = Color(0.2, 0.7, 0.3)
    top.size = Vector2(60, gap_y - 80)
    top.position = Vector2(520, 0)
    add_child(top)
    var bottom = ColorRect.new()
    bottom.color = Color(0.2, 0.7, 0.3)
    bottom.size = Vector2(60, 720 - (gap_y + 80))
    bottom.position = Vector2(520, gap_y + 80)
    add_child(bottom)

func add_score() -> void:
    score += 1
    score_label.text = str(score)
""")

_GAME_SCRIPT_GENERIC = textwrap.dedent("""\
extends Node2D

func _ready() -> void:
    print("Sentinel game ready — extend scripts/game.gd")
""")

_PLAYER_SCRIPT = textwrap.dedent("""\
extends CharacterBody2D

const GRAVITY := 980.0
const FLAP := -320.0

func _physics_process(delta: float) -> void:
    if Input.is_action_just_pressed("ui_accept") or Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
        velocity.y = FLAP
    velocity.y += GRAVITY * delta
    move_and_slide()
    if position.y > 720 or position.y < 0:
        get_parent().get_tree().reload_current_scene()
""")

_PIPE_SCRIPT = textwrap.dedent("""\
# Pipe obstacle helper — used by game.gd spawn logic
extends Node
""")

_EXPORT_CFG = """\
[preset.0]
name="Windows Desktop"
platform="Windows Desktop"
runnable=true
"""
