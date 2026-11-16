"""Shared rendering constants and declarative tables."""
from __future__ import annotations
from gcodeproducer.core.geometry.geometry_constants import BINARY_BOX_EDGES, BINARY_BOX_FACES
import numpy as np
from gcodeproducer.core.gcode.toolpath import CUT, EXTRUDE, RAPID, TRAVEL

DEFAULT_RECT = (0.0, 0.0, 220.0, 220.0, 250.0)

MODEL_COLOR = (0.30, 0.58, 0.92)

OVERHANG_COLOR = (0.92, 0.30, 0.26)

OUTSIDE_COLOR = (0.95, 0.62, 0.20)

BLOCK_COLOR = (0.25, 0.85, 0.45)

BLOCK_SEL_COLOR = (1.0, 0.85, 0.2)

BLOCK_DEL_COLOR = (1.0, 0.25, 0.25)

_BOX_FACES = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6), (0, 4, 5), (0, 5, 1),
              (1, 5, 6), (1, 6, 2), (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0)]

_BOX_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]

CLIP = """
uniform int uClipOn;
uniform vec4 uClip;
uniform float uSlab;
bool clipped(vec3 w) {
    if (uClipOn == 0) return false;
    float d = dot(uClip.xyz, w) - uClip.w;
    if (uSlab > 0.0) return abs(d) > uSlab * 0.5;
    return d > 0.0;
}
"""

SEG_VS = """
#version 330 core
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec2 aInfo;   // line index, layer
layout(location = 2) in vec4 aColor;  // alpha = visible
uniform mat4 uMVP;
uniform float uCursor;
uniform float uSel;
uniform float uLayerMin;
uniform float uLayerMax;
uniform int uDim;
uniform int uNoFilter;
uniform float uPointSize;
out vec3 vWorld;
out vec4 vColor;
out float vHidden;
void main() {
    vWorld = aPos;
    float h = 0.0;
    vec3 c = aColor.rgb;
    if (uNoFilter == 0) {
        if (aColor.a < 0.5) h = 1.0;
        if (aInfo.x > uCursor + 0.5) h = 1.0;
        if (aInfo.y < uLayerMin - 0.5 || aInfo.y > uLayerMax + 0.5) h = 1.0;
        if (uDim == 1 && aInfo.y < uLayerMax - 0.5) c *= 0.35;
        if (abs(aInfo.x - uCursor) < 0.5) c = vec3(1.0, 1.0, 1.0);
        if (abs(aInfo.x - uSel) < 0.5) c = vec3(0.0, 1.0, 1.0);
    }
    vColor = vec4(c, 1.0);
    vHidden = h;
    gl_PointSize = uPointSize;
    gl_Position = uMVP * vec4(aPos, 1.0);
}
"""

TUBE_GS = """
#version 330 core
layout(lines) in;
layout(triangle_strip, max_vertices = 4) out;
in vec3 vWorld[];
in vec4 vColor[];
in float vHidden[];
uniform mat4 uMVP;
uniform vec3 uEye;
uniform vec3 uViewDir;
uniform int uOrtho;
uniform float uHalfW;
out vec3 gWorld;
out vec4 gColor;
out float gAcross;
void emitv(vec3 p, float a, vec4 c) {
    gWorld = p; gColor = c; gAcross = a;
    gl_Position = uMVP * vec4(p, 1.0);
    EmitVertex();
}
void main() {
    if (vHidden[0] > 0.5 || vHidden[1] > 0.5) return;
    vec3 p0 = vWorld[0];
    vec3 p1 = vWorld[1];
    vec3 d = p1 - p0;
    float len = length(d);
    if (len < 1e-6) return;
    d /= len;
    vec3 toEye = (uOrtho == 1) ? -uViewDir : normalize(uEye - 0.5 * (p0 + p1));
    vec3 s = cross(d, toEye);
    if (length(s) < 1e-5) {
        s = cross(d, vec3(0.0, 0.0, 1.0));
        if (length(s) < 1e-5) s = vec3(1.0, 0.0, 0.0);
    }
    s = normalize(s) * uHalfW;
    vec3 e = d * uHalfW * 0.6;
    emitv(p0 - e - s, -1.0, vColor[0]);
    emitv(p0 - e + s,  1.0, vColor[0]);
    emitv(p1 + e - s, -1.0, vColor[1]);
    emitv(p1 + e + s,  1.0, vColor[1]);
    EndPrimitive();
}
"""

TUBE_FS = """
#version 330 core
in vec3 gWorld;
in vec4 gColor;
in float gAcross;
out vec4 frag;
""" + CLIP + """
void main() {
    if (clipped(gWorld)) discard;
    float a = gAcross;
    float nz = sqrt(max(0.0, 1.0 - a * a));
    float diff = 0.30 + 0.70 * nz;
    float spec = pow(nz, 28.0) * 0.22;
    frag = vec4(gColor.rgb * diff + vec3(spec), 1.0);
}
"""

LINE_FS = """
#version 330 core
in vec3 vWorld;
in vec4 vColor;
in float vHidden;
uniform float uAlpha;
out vec4 frag;
""" + CLIP + """
void main() {
    if (vHidden > 0.5 || clipped(vWorld)) discard;
    frag = vec4(vColor.rgb, uAlpha);
}
"""

POINT_FS = """
#version 330 core
in vec3 vWorld;
in vec4 vColor;
in float vHidden;
uniform int uNoClip;
out vec4 frag;
""" + CLIP + """
void main() {
    if (vHidden > 0.5) discard;
    if (uNoClip == 0 && clipped(vWorld)) discard;
    vec2 c = gl_PointCoord * 2.0 - 1.0;
    float r = dot(c, c);
    if (r > 1.0) discard;
    frag = vec4(vColor.rgb * (1.0 - 0.35 * r), 1.0);
}
"""

FLAT_VS = """
#version 330 core
layout(location = 0) in vec3 aPos;
uniform mat4 uMVP;
void main() { gl_Position = uMVP * vec4(aPos, 1.0); }
"""

FLAT_FS = """
#version 330 core
uniform vec4 uColor;
out vec4 frag;
void main() { frag = uColor; }
"""

MESH_VS = """
#version 330 core
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec4 aColor;
uniform mat4 uMVP;
out vec3 vWorld;
out vec3 vNormal;
out vec4 vColor;
void main() {
    vWorld = aPos;
    vNormal = aNormal;
    vColor = aColor;
    gl_Position = uMVP * vec4(aPos, 1.0);
}
"""

MESH_FS = """
#version 330 core
in vec3 vWorld;
in vec3 vNormal;
in vec4 vColor;
uniform vec3 uEye;
uniform vec3 uViewDir;
uniform int uOrtho;
uniform float uHighlight;
uniform vec3 uKey;          // key light direction (towards the light), camera relative
out vec4 frag;
void main() {
    vec3 n = normalize(vNormal);
    vec3 V = (uOrtho == 1) ? -uViewDir : normalize(uEye - vWorld);
    if (dot(n, V) < 0.0) n = -n;                 // two sided
    float key = max(dot(n, uKey), 0.0);
    float fill = max(dot(n, V), 0.0);
    float diff = 0.18 + 0.55 * key + 0.27 * fill;
    vec3 h = normalize(uKey + V);
    float spec = pow(max(dot(n, h), 0.0), 48.0) * 0.20;
    vec3 c = vColor.rgb * diff + vec3(spec);
    c = mix(c, vec3(1.0), uHighlight);
    frag = vec4(c, vColor.a);
}
"""

COLOR_MODES = [("feature", "Feature type"), ("type", "Move type"), ("speed", "Speed / feed"),
               ("layer", "Layer"), ("changes", "Changes"), ("operation", "Operation (CAM)"),
               ("engagement", "Tool engagement (CAM)")]

KIND_COLORS = {EXTRUDE: (1.0, 0.55, 0.15), TRAVEL: (0.35, 0.65, 1.0), CUT: (1.0, 0.75, 0.2), RAPID: (1.0, 0.25, 0.25)}

TRAVEL_COLOR = (0.35, 0.65, 1.0)

RAPID_COLOR = (1.0, 0.3, 0.3)

CHANGED_COLOR = (1.0, 0.1, 0.9)

UNCHANGED_COLOR = (0.42, 0.42, 0.45)

_RAMP = np.array([[0.1, 0.2, 0.9], [0.0, 0.8, 0.9], [0.1, 0.85, 0.2], [1.0, 0.9, 0.0], [1.0, 0.15, 0.1]], np.float32)

HIGHLIGHT_PASSES = ((False, 0.35), (True, 1.0))

CAMERA_ANGLES = {"iso": (-60, 35), "top": (-90, 89.9), "bottom": (-90, -89.9), "front": (-90, 0),
                 "back": (90, 0), "left": (180, 0), "right": (0, 0)}
