"""Generate docs/assets/palette.svg: the Tracex design tokens as a swatch sheet.

    python docs/scripts/build_palette_svg.py

Values mirror frontend/src/app/globals.css (themselves ported from the golden
tracex-workspace.html). Update both together.
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "palette.svg"

SURFACES = {
    "dark": [
        ("bg", "#0B0F17"),
        ("panel", "#0D121D"),
        ("card", "#131B2E"),
        ("line", "#1E293B"),
        ("ink", "#E2E8F0"),
        ("sub", "#94A3B8"),
        ("muted", "#64748B"),
    ],
    "light": [
        ("bg", "#F7F8FA"),
        ("panel", "#FFFFFF"),
        ("card", "#F1F5F9"),
        ("line", "#E2E8F0"),
        ("ink", "#0F172A"),
        ("sub", "#475569"),
        ("muted", "#64748B"),
    ],
}
ACCENTS = {
    "dark": [("mint · focus", "#10B981"), ("trace · call site", "#38BDF8"), ("violet · graph", "#A78BFA")],
    "light": [("mint · focus", "#059669"), ("trace · call site", "#0284C7"), ("violet · graph", "#7C3AED")],
}
SYNTAX = {
    "dark": [
        ("kw", "#C4A7FF"),
        ("def", "#34D399"),
        ("fn", "#8ECBF0"),
        ("type", "#F0C674"),
        ("str", "#E9D8A6"),
        ("num", "#F4A261"),
        ("self", "#F0A6C8"),
        ("deco", "#67D4E8"),
        ("bi", "#6FD3C6"),
        ("com", "#718096"),
        ("p", "#8A97AB"),
        ("default", "#D6DDE8"),
    ],
    "light": [
        ("kw", "#7C3AED"),
        ("def", "#047857"),
        ("fn", "#0369A1"),
        ("type", "#B45309"),
        ("str", "#A16207"),
        ("num", "#C2410C"),
        ("self", "#BE185D"),
        ("deco", "#0E7490"),
        ("bi", "#0F766E"),
        ("com", "#64748B"),
        ("p", "#64748B"),
        ("default", "#1E293B"),
    ],
}
FONT = "Inter, 'Segoe UI', system-ui, sans-serif"
MONO = "'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace"


def panel(mode: str, x0: float) -> str:
    bg = SURFACES[mode][1][1]
    ink = SURFACES[mode][4][1]
    sub = SURFACES[mode][6][1]
    line = SURFACES[mode][3][1]
    out = [
        f'<rect x="{x0}" y="0" width="560" height="430" rx="16" fill="{bg}" stroke="{line}"/>',
        f'<text x="{x0 + 28}" y="40" font-family="{FONT}" font-size="15" font-weight="600" fill="{ink}">{mode.title()} theme</text>',
    ]

    def row(
        y: float, title: str, items: list[tuple[str, str]], size: int, gap: int, mono: bool = False
    ) -> None:
        out.append(
            f'<text x="{x0 + 28}" y="{y}" font-family="{FONT}" font-size="10.5" letter-spacing="1" fill="{sub}">{title}</text>'
        )
        x = x0 + 28
        for name, hexv in items:
            out.append(
                f'<rect x="{x}" y="{y + 10}" width="{size}" height="{size}" rx="8" fill="{hexv}" stroke="{line}"/>'
            )
            out.append(
                f'<text x="{x}" y="{y + size + 26}" font-family="{MONO if mono else FONT}" font-size="10.5" fill="{ink}">{name}</text>'
            )
            out.append(
                f'<text x="{x}" y="{y + size + 40}" font-family="{MONO}" font-size="9.5" fill="{sub}">{hexv}</text>'
            )
            x += size + gap

    row(72, "SURFACES &amp; INK", SURFACES[mode], 56, 18)
    row(192, "ACCENTS", ACCENTS[mode], 56, 112)
    out.append(
        f'<text x="{x0 + 28}" y="312" font-family="{FONT}" font-size="10.5" letter-spacing="1" fill="{sub}">SYNTAX TOKENS (tk-*)</text>'
    )
    x, y = x0 + 28, 330
    for i, (name, hexv) in enumerate(SYNTAX[mode]):
        cx, cy = x + (i % 6) * 84, y + (i // 6) * 42
        out.append(f'<circle cx="{cx + 7}" cy="{cy + 9}" r="6" fill="{hexv}"/>')
        out.append(
            f'<text x="{cx + 20}" y="{cy + 13}" font-family="{MONO}" font-size="11" fill="{hexv}">{name}</text>'
        )
        out.append(
            f'<text x="{cx + 20}" y="{cy + 27}" font-family="{MONO}" font-size="9" fill="{sub}">{hexv}</text>'
        )
    return "\n".join(out)


def build() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1140" height="430" viewBox="0 0 1140 430" role="img" '
        'aria-label="Tracex design tokens: surfaces, accents and syntax colours for dark and light themes">\n'
        + panel("dark", 0)
        + "\n"
        + panel("light", 580)
        + "\n</svg>\n"
    )


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}")
