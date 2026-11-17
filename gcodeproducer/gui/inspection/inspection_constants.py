"""Shared inspection (Preview playback) constants."""

# (key, label, tooltip) of the transport buttons, left to right (as in GCodeTools)
TRANSPORT_BUTTONS = (
    ("start", "\u23ee", "Start of the program"),
    ("prev_layer", "\u23ea", "Previous layer (PgDown)"),
    ("prev_line", "\u25c0", "Previous move (Left)"),
    ("play", "\u25b6", "Play / pause (Space)"),
    ("next_line", "\u25b6|", "Next move (Right)"),
    ("next_layer", "\u23e9", "Next layer (PgUp)"),
    ("end", "\u23ed", "End: show everything"),
)
PLAY_ICON, PAUSE_ICON = "\u25b6", "\u23f8"

PLAY_INTERVAL_MS = 16             # timer tick (about 60 frames per second)
PLAY_SPEED_STEPS = 1000           # speed slider resolution
PLAY_SPEED_DECADES = 4.7          # slider spans 10**0 .. 10**4.7 lines per second (1 .. 50,000)
PLAY_SPEED_DEFAULT = 400          # about 40 lines per second
