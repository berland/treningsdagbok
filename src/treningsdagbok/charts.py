"""Tiny dependency-free SVG stacked bar chart."""

from html import escape

COLORS = ["#bb0000", "#00aa00", "#0000aa", "#770077", "#bbbb00", "#000000"]


def bar_chart(labels, series, width=900, height=350):
    left, right, top, bottom = 50, 20, 20, 50
    pw, ph = width - left - right, height - top - bottom
    peak = max([sum(col) for col in zip(*series.values(), strict=True)] or [0])
    step = next(
        (s for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000) if peak / s <= 8), 1000
    )
    ymax = max(step, -(-peak // step) * step)
    n = len(labels)

    slot = pw / n if n else pw
    bar_w = slot * 0.7

    def x(i):
        return left + slot * (i + 0.5)

    def y(v):
        return top + ph - ph * v / ymax

    out = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}" '
            f'font-family="sans-serif" font-size="11">'
        ),
        f'<rect width="{width}" height="{height}" fill="white"/>',
    ]
    v = 0
    while v <= ymax + 1e-9:
        out.append(
            f'<line x1="{left}" x2="{width - right}" y1="{y(v):.1f}" '
            f'y2="{y(v):.1f}" stroke="#ddd"/>'
        )
        out.append(
            f'<text x="{left - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{v:g}</text>'
        )
        v += step
    out.append(
        f'<text x="12" y="{top + ph / 2}" text-anchor="middle" '
        f'transform="rotate(-90 12 {top + ph / 2})">Timer</text>'
    )
    every = max(1, n // 12)
    for i, label in enumerate(labels):
        if i % every == 0:
            out.append(
                f'<text x="{x(i):.1f}" y="{height - bottom + 16}" '
                f'text-anchor="middle">{escape(str(label))}</text>'
            )
    base = [0] * n
    for color, (name, vals) in zip(COLORS, series.items(), strict=False):
        for i, v in enumerate(vals):
            if v > 0:
                out.append(
                    f'<rect x="{x(i) - bar_w / 2:.1f}" y="{y(base[i] + v):.1f}" '
                    f'width="{bar_w:.1f}" height="{ph * v / ymax:.1f}" '
                    f'fill="{color}"><title>{escape(str(labels[i]))}: '
                    f"{escape(name)} {v:.1f}</title></rect>"
                )
                base[i] += v
    for i, (color, name) in enumerate(zip(COLORS, series, strict=False)):
        lx = left + 10 + i * 90
        out.append(
            f'<rect x="{lx}" y="{height - 22}" width="12" height="10" fill="{color}"/>'
        )
        out.append(f'<text x="{lx + 16}" y="{height - 13}">{escape(name)}</text>')
    out.append("</svg>")
    return "\n".join(out)
