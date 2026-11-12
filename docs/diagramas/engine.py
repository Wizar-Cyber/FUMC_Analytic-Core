"""Motor mínimo de diagramas de arquitectura (SVG autocontenido + PNG).

Sin dependencias externas: cada diagrama se describe con nodos en coordenadas de
píxel, agrupaciones y conexiones. Los logos se incrustan en base64 desde
``docs/imagenes/logos`` para que el SVG sea portable. El PNG se exporta con Chrome
o Edge en modo headless si están disponibles.
"""

from __future__ import annotations

import base64
import html
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
LOGOS = DOCS / "imagenes" / "logos"
SVG_DIR = DOCS / "diagramas"
PNG_DIR = DOCS / "imagenes"

FONT = "Segoe UI, Inter, Helvetica, Arial, sans-serif"
INK = "#1f2d36"
MUTED = "#5b6b75"
LINE = "#7d8f99"

# Colores de agrupación por capa (relleno suave, borde y título).
PALETTE = {
    "azure": ("#eef6fc", "#0078d4"),
    "data": ("#f2f8ee", "#3f8f29"),
    "ml": ("#fff6e8", "#c46a00"),
    "agents": ("#f5effc", "#7a3db8"),
    "front": ("#eaf7f7", "#0d8a8a"),
    "security": ("#fdeef2", "#c2185b"),
    "ops": ("#f1f3f5", "#5b6b75"),
    "external": ("#ffffff", "#9aa8b1"),
}

EDGE_COLORS = {
    "default": LINE,
    "data": "#3f8f29",
    "ml": "#c46a00",
    "agents": "#7a3db8",
    "azure": "#0078d4",
    "security": "#c2185b",
}


@dataclass
class Node:
    id: str
    label: str
    x: float
    y: float
    icon: str | None = None
    sub: str = ""
    w: float = 150
    h: float = 0
    kind: str = "box"  # box | pill | text

    def __post_init__(self) -> None:
        if not self.h:
            lines = self.label.count("\n") + 1 + (self.sub.count("\n") + 1 if self.sub else 0)
            self.h = (52 if self.icon else 18) + lines * 15 + 10


@dataclass
class Cluster:
    label: str
    members: list[str]
    tone: str = "azure"
    pad: float = 18
    icon: str | None = None
    box: tuple[float, float, float, float] | None = None  # x, y, w, h explícito


@dataclass
class Edge:
    a: str
    b: str
    label: str = ""
    tone: str = "default"
    dashed: bool = False
    route: str = "straight"  # straight | hv | vh
    both: bool = False
    label_pos: float = 0.5
    dx: float = 0
    dy: float = 0


@dataclass
class Diagram:
    name: str
    title: str
    width: int
    height: int
    subtitle: str = ""
    nodes: dict[str, Node] = field(default_factory=dict)
    clusters: list[Cluster] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    notes: list[tuple[float, float, str]] = field(default_factory=list)

    # --- API declarativa -------------------------------------------------
    def node(self, id: str, label: str, x: float, y: float, icon: str | None = None, sub: str = "", **kw) -> Node:
        node = Node(id, label, x, y, icon, sub, **kw)
        self.nodes[id] = node
        return node

    def group(self, label: str, members: list[str], tone: str = "azure", **kw) -> None:
        self.clusters.append(Cluster(label, members, tone, **kw))

    def link(self, a: str, b: str, label: str = "", **kw) -> None:
        self.edges.append(Edge(a, b, label, **kw))

    def note(self, x: float, y: float, text: str) -> None:
        self.notes.append((x, y, text))

    # --- Renderizado ------------------------------------------------------
    def svg(self) -> str:
        out: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}" '
            f'font-family="{FONT}">',
            "<defs>",
        ]
        for tone, color in EDGE_COLORS.items():
            out.append(
                f'<marker id="arrow-{tone}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
                f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>'
            )
        out.append("</defs>")
        out.append(f'<rect width="100%" height="100%" fill="#ffffff"/>')
        out.append(_text(24, 34, self.title, 20, INK, weight=700, anchor="start"))
        if self.subtitle:
            out.append(_text(24, 56, self.subtitle, 12.5, MUTED, anchor="start"))

        for cluster in self.clusters:
            out.append(self._cluster(cluster))
        for edge in self.edges:
            out.append(self._edge(edge))
        for node in self.nodes.values():
            out.append(self._node(node))
        for x, y, text in self.notes:
            for index, line in enumerate(text.split("\n")):
                out.append(_text(x, y + index * 15, line, 11.5, MUTED, anchor="start", italic=True))
        out.append("</svg>")
        return "\n".join(out)

    def _bounds(self, cluster: Cluster) -> tuple[float, float, float, float]:
        if cluster.box:
            return cluster.box
        members = [self.nodes[m] for m in cluster.members]
        left = min(n.x - n.w / 2 for n in members) - cluster.pad
        right = max(n.x + n.w / 2 for n in members) + cluster.pad
        top = min(n.y - n.h / 2 for n in members) - cluster.pad - 22
        bottom = max(n.y + n.h / 2 for n in members) + cluster.pad
        return left, top, right - left, bottom - top

    def _cluster(self, cluster: Cluster) -> str:
        x, y, w, h = self._bounds(cluster)
        fill, stroke = PALETTE[cluster.tone]
        parts = [
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.4" stroke-dasharray="{"6 4" if cluster.tone == "external" else "none"}"/>'
        ]
        tx = x + 12
        if cluster.icon:
            parts.append(_image(cluster.icon, x + 10, y + 6, 18))
            tx += 22
        parts.append(_text(tx, y + 20, cluster.label, 12.5, stroke, weight=700, anchor="start"))
        return "\n".join(parts)

    def _node(self, node: Node) -> str:
        left, top = node.x - node.w / 2, node.y - node.h / 2
        parts = []
        if node.kind == "box":
            parts.append(
                f'<rect x="{left:.1f}" y="{top:.1f}" width="{node.w:.1f}" height="{node.h:.1f}" rx="9" '
                f'fill="#ffffff" stroke="#c9d4da" stroke-width="1.2"/>'
            )
        elif node.kind == "pill":
            parts.append(
                f'<rect x="{left:.1f}" y="{top:.1f}" width="{node.w:.1f}" height="{node.h:.1f}" rx="{node.h / 2:.1f}" '
                f'fill="#f7f9fa" stroke="#c9d4da" stroke-width="1.2"/>'
            )
        cursor = top + 10
        if node.icon:
            parts.append(_image(node.icon, node.x - 20, cursor, 40))
            cursor += 46
        for line in node.label.split("\n"):
            cursor += 13
            parts.append(_text(node.x, cursor, line, 12.5, INK, weight=600))
            cursor += 2
        if node.sub:
            for line in node.sub.split("\n"):
                cursor += 14
                parts.append(_text(node.x, cursor, line, 10.5, MUTED))
        return "\n".join(parts)

    def _anchor(self, node: Node, toward: tuple[float, float]) -> tuple[float, float]:
        dx, dy = toward[0] - node.x, toward[1] - node.y
        if dx == 0 and dy == 0:
            return node.x, node.y
        sx = (node.w / 2) / abs(dx) if dx else math.inf
        sy = (node.h / 2) / abs(dy) if dy else math.inf
        scale = min(sx, sy)
        return node.x + dx * scale, node.y + dy * scale

    def _side(self, node: Node, horizontal: bool, sign: float) -> tuple[float, float]:
        if horizontal:
            return node.x + sign * node.w / 2, node.y
        return node.x, node.y + sign * node.h / 2

    def _edge(self, edge: Edge) -> str:
        a, b = self.nodes[edge.a], self.nodes[edge.b]
        color = EDGE_COLORS.get(edge.tone, LINE)
        if edge.route == "hv":
            start = self._side(a, True, 1 if b.x > a.x else -1)
            end = self._side(b, False, -1 if b.y > a.y else 1)
            points = [start, (end[0], start[1]), end]
        elif edge.route == "vh":
            start = self._side(a, False, 1 if b.y > a.y else -1)
            end = self._side(b, True, -1 if b.x > a.x else 1)
            points = [start, (start[0], end[1]), end]
        else:
            start = self._anchor(a, (b.x, b.y))
            end = self._anchor(b, (a.x, a.y))
            points = [start, end]
        path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(points))
        dash = ' stroke-dasharray="5 4"' if edge.dashed else ""
        start_marker = f' marker-start="url(#arrow-{edge.tone})"' if edge.both else ""
        parts = [
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.6"{dash}{start_marker} '
            f'marker-end="url(#arrow-{edge.tone})"/>'
        ]
        if edge.label:
            lx, ly = _point_on(points, edge.label_pos)
            lx += edge.dx
            ly += edge.dy
            lines = edge.label.split("\n")
            width = max(len(line) for line in lines) * 5.9 + 12
            height = len(lines) * 13 + 6
            parts.append(
                f'<rect x="{lx - width / 2:.1f}" y="{ly - height / 2:.1f}" width="{width:.1f}" height="{height:.1f}" '
                f'rx="4" fill="#ffffff" fill-opacity="0.94" stroke="{color}" stroke-opacity="0.35"/>'
            )
            for index, line in enumerate(lines):
                parts.append(_text(lx, ly - height / 2 + 14 + index * 13, line, 10.5, INK))
        return "\n".join(parts)


def _point_on(points: list[tuple[float, float]], ratio: float) -> tuple[float, float]:
    segments = list(zip(points, points[1:]))
    lengths = [math.dist(p, q) for p, q in segments]
    target = sum(lengths) * ratio
    for (p, q), length in zip(segments, lengths):
        if target <= length and length:
            t = target / length
            return p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
        target -= length
    return points[-1]


def _text(x, y, text, size, color, weight=400, anchor="middle", italic=False) -> str:
    style = ' font-style="italic"' if italic else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" font-weight="{weight}" '
        f'text-anchor="{anchor}"{style}>{html.escape(text)}</text>'
    )


_ICON_CACHE: dict[str, tuple[str, int, int]] = {}


def _image(name: str, x: float, y: float, size: float) -> str:
    """Incrusta un logo respetando su proporción (los logos apaisados se ensanchan)."""
    if name not in _ICON_CACHE:
        data = (LOGOS / f"{name}.png").read_bytes()
        width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        _ICON_CACHE[name] = (base64.b64encode(data).decode("ascii"), width, height)
    encoded, width, height = _ICON_CACHE[name]
    ratio = width / height if height else 1
    draw_h = size if ratio <= 1 else min(size, size * 2.4 / ratio)
    draw_w = draw_h * ratio
    left = x + (size - draw_w) / 2
    top = y + (size - draw_h) / 2
    return (
        f'<image x="{left:.1f}" y="{top:.1f}" width="{draw_w:.1f}" height="{draw_h:.1f}" '
        f'href="data:image/png;base64,{encoded}" xlink:href="data:image/png;base64,{encoded}"/>'
    )


def _browser() -> str | None:
    candidates = [
        os.environ.get("CHROME_PATH", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        shutil.which("msedge") or "",
    ]
    return next((c for c in candidates if c and Path(c).exists()), None)


def render(diagram: Diagram, png: bool = True) -> Path:
    SVG_DIR.mkdir(parents=True, exist_ok=True)
    svg_path = SVG_DIR / f"{diagram.name}.svg"
    svg_path.write_text(diagram.svg(), encoding="utf-8")
    browser = _browser()
    if png and browser:
        PNG_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text(
                "<!doctype html><html><body style='margin:0'>"
                f"<img src='{svg_path.as_uri()}' width='{diagram.width}' height='{diagram.height}'></body></html>",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    browser,
                    "--headless=new",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    "--force-device-scale-factor=2",
                    f"--window-size={diagram.width},{diagram.height}",
                    f"--screenshot={PNG_DIR / (diagram.name + '.png')}",
                    page.as_uri(),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
    return svg_path
