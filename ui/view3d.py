"""Interactive 3D view of the built pallet (Plotly)."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from pallet_builder import Pallet

# Above this many cases the 3D view draws each layer as one block to stay responsive.
MAX_3D_CASES = 6000

_BOX_FACES = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
              (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
_BOX_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]


def _corners(x, y, z, length, width, height):
    return [
        (x, y, z), (x + length, y, z), (x + length, y + width, z), (x, y + width, z),
        (x, y, z + height), (x + length, y, z + height), (x + length, y + width, z + height), (x, y + width, z + height),
    ]


def _box_mesh(boxes: list[tuple], colors: list[str], **kwargs) -> go.Mesh3d:
    """All boxes as one mesh trace (one trace per box would make large loads sluggish)."""
    xs, ys, zs, i, j, k, face_colors = [], [], [], [], [], [], []
    for n, (box, color) in enumerate(zip(boxes, colors)):
        for cx, cy, cz in _corners(*box):
            xs.append(cx)
            ys.append(cy)
            zs.append(cz)
        for a, b, c in _BOX_FACES:
            i.append(8 * n + a)
            j.append(8 * n + b)
            k.append(8 * n + c)
            face_colors.append(color)
    return go.Mesh3d(x=xs, y=ys, z=zs, i=i, j=j, k=k, facecolor=face_colors, flatshading=True,
                     hoverinfo="skip", lighting={"ambient": 0.75, "diffuse": 0.6, "specular": 0.05}, **kwargs)


def _box_edges(boxes: list[tuple], color: str, width: float = 1.5, dash: str | None = None) -> go.Scatter3d:
    xs, ys, zs = [], [], []
    for box in boxes:
        corners = _corners(*box)
        for a, b in _BOX_EDGES:
            for point in (corners[a], corners[b], (None, None, None)):
                xs.append(point[0])
                ys.append(point[1])
                zs.append(point[2])
    return go.Scatter3d(x=xs, y=ys, z=zs, mode="lines", hoverinfo="skip",
                        line={"color": color, "width": width, "dash": dash})


def render(pallet: Pallet, result) -> None:
    deck = pallet.deck_height or 0.0
    layer_index = {z: n for n, z in enumerate(sorted({p.z for p in result.placements}))}
    shades = ["#3b82f6", "#93c5fd"]  # alternate layers so the stack reads clearly

    if len(result.placements) <= MAX_3D_CASES:
        boxes = [(p.x, p.y, p.z + deck, p.length, p.width, p.height) for p in result.placements]
        colors = [shades[layer_index[p.z] % 2] for p in result.placements]
        draw_edges = True
    else:
        # One block per layer: the bounding box of that layer's cases.
        boxes, colors = [], []
        for z, n in layer_index.items():
            layer = [p for p in result.placements if p.z == z]
            x0, y0 = min(p.x for p in layer), min(p.y for p in layer)
            x1, y1 = max(p.x + p.length for p in layer), max(p.y + p.width for p in layer)
            boxes.append((x0, y0, z + deck, x1 - x0, y1 - y0, layer[0].height))
            colors.append(shades[n % 2])
        draw_edges = True
        st.caption(f"{len(result.placements):,} cases: each layer is drawn as a single block.")

    traces = []
    if deck:
        deck_box = [(0.0, 0.0, 0.0, pallet.length, pallet.width, deck)]
        traces += [_box_mesh(deck_box, ["#b45309"]), _box_edges(deck_box, "#78350f", 2)]
    traces.append(_box_mesh(boxes, colors))
    if draw_edges:
        traces.append(_box_edges(boxes, "#1e3a8a", 1.2))
    if pallet.height is not None:
        envelope = [(0.0, 0.0, 0.0, pallet.length, pallet.width, pallet.height)]
        traces.append(_box_edges(envelope, "#ef4444", 2, dash="dash"))

    def camera(eye_x, eye_y, eye_z, up_y=0.0, up_z=1.0):
        return {"scene.camera": {"eye": {"x": eye_x, "y": eye_y, "z": eye_z}, "up": {"x": 0, "y": up_y, "z": up_z}}}

    views = [("Iso", camera(1.5, -1.5, 1.1)), ("Front", camera(0, -2.3, 0.2)),
             ("Side", camera(2.3, 0, 0.2)), ("Top", camera(0, 0, 2.6, up_y=1.0, up_z=0.0))]
    fig = go.Figure(traces)
    unit = pallet.unit
    fig.update_layout(
        height=560,
        margin={"l": 0, "r": 0, "t": 30, "b": 0},
        showlegend=False,
        scene={
            "aspectmode": "data",
            "xaxis": {"title": f"Length ({unit})"},
            "yaxis": {"title": f"Width ({unit})"},
            "zaxis": {"title": f"Height ({unit})"},
            "camera": views[0][1]["scene.camera"],
            "dragmode": "turntable",  # spin about the vertical axis so the pallet stays upright
        },
        updatemenus=[{
            "type": "buttons", "direction": "right", "x": 0, "y": 1.07, "xanchor": "left",
            "showactive": False, "pad": {"r": 4},
            "buttons": [{"label": label, "method": "relayout", "args": [args]} for label, args in views],
        }],
    )
    st.plotly_chart(fig, width="stretch", config={
        "displaylogo": False,
        "scrollZoom": True,
        "modeBarButtonsToRemove": ["orbitRotation", "pan3d"],
    })
    st.caption("Drag to spin · scroll to zoom · buttons reset the viewpoint. "
               "Brown = pallet deck, red dashes = max build height.")
