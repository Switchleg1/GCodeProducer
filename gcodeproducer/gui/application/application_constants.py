"""Shared application constants and declarative tables."""
from __future__ import annotations

MODEL_FILTER = "Meshes (*.stl)"

SHOW_OPTIONS = (("show_travel", "Travel / rapid moves", "colors"),
                                ("show_retracts", "Retraction points", "colors"),
                                ("show_extrude", "Toolpaths", "colors"),
                                ("show_material", "Material", "view"),
                                ("show_tool", "Tool head", "view"), ("show_grid", "Grid", "view"),
                                ("dim_lower", "Dim layers below top", "view"))

CAMERA_VIEW_KEYS = ("iso", "top", "front", "right")

CAMERA_VIEWS = tuple((name.title(), name) for name in CAMERA_VIEW_KEYS)

ROTATION_BUTTONS = ((2, -90), (3, 90))

THEME_COLORS = {
    "dark": (45, 47, 52), "base": (32, 34, 38), "text": (220, 222, 226),
    "highlight": (60, 120, 200), "selected": (255, 255, 255), "disabled": (120, 120, 120),
}

THEME_ROLES = {
    "Window": "dark", "WindowText": "text", "Base": "base", "AlternateBase": "dark",
    "Text": "text", "Button": "dark", "ButtonText": "text", "ToolTipBase": "base",
    "ToolTipText": "text", "Highlight": "highlight", "HighlightedText": "selected",
}

THEME_STYLESHEET = ("QToolButton#sectionHeader { background: #3a3d44; border: none; border-radius: 3px;"
        "  padding: 3px 6px; text-align: left; font-weight: bold; color: #dde; }"
        "QToolButton#sectionHeader:hover { background: #454952; }"
        "QToolButton#sectionHeader:checked { background: #34557f; color: white; }"
        "QFrame#sectionBody { background: #2b2d32; border-radius: 3px; }"
        "QToolButton#subsectionHeader { background: #33363c; border: none; border-radius: 3px;"
        "  padding: 2px 6px; text-align: left; color: #cdd; }"
        "QToolButton#subsectionHeader:hover { background: #3d4048; }"
        "QToolButton#subsectionHeader:checked { background: #2f3f55; color: #e6ecf5; }"
        "QToolButton#modeButton { background: #34373d; border: 1px solid #44474e; padding: 5px 14px;"
        "  font-weight: bold; color: #ccd; }"
        "QToolButton#modeButton:checked { background: #3c78c8; color: white; border-color: #3c78c8; }"
        "QToolButton#modeButton:disabled { color: #666; }"
        "QPushButton:checked { background: #3c78c8; color: white; border: 1px solid #5a8fd8; }")

ACTION_BUTTON_HEIGHT = 34          # Slice / Generate paths and Save G-code
ACTION_BUTTON_STRETCH = (7, 3)     # width share of the two buttons
