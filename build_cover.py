#!/usr/bin/env python3
"""
build_cover.py

One-shot cover builder + optional MP3 cover embedding.

- Finds your art in the base folder (default /mnt/ai_data/BedtimeStories)
- Resizes art to 3000x3000 (CPU-friendly, Pillow)
- Renders an SVG cover (gradient + art + title/subtitle/badge) and exports JPG
- Optionally embeds that cover.jpg into each MP3 in the story folder via ffmpeg

Usage:
  ./build_cover.py <safeTheme>
      [--title "Friendly Dinosaurs"]      # optional; auto-derived from safeTheme if omitted
      [--subtitle "Age 3–7 • Sharing makes everyone feel safe and happy"]
      [--badge "Includes 3 narrator voices"]
      [--palette warm|cool|forest|/path/palette.json]
      [--art friendly_dinosaurs_art.png]  # optional explicit file in base or absolute path
      [--base /mnt/ai_data/BedtimeStories]
      [--out-name friendly_dinosaurs_cover.jpg]
      [--no-embed]                        # skip embedding cover into MP3s

Deps:
  sudo apt-get install imagemagick ffmpeg  (ffmpeg only needed for embedding)
  pip install jinja2 pillow
  (optional: pip install cairosvg or sudo apt-get install inkscape)
"""
import argparse, os, sys, json, tempfile, shutil, subprocess, textwrap
from pathlib import Path
from typing import Optional, List
from jinja2 import Template
from PIL import Image, ImageFilter

# ---------- Defaults ----------
DEFAULT_BASE = os.environ.get("STORY_BASE", "/mnt/ai_data/BedtimeStories")
PALETTES = {
    "warm":   {"BG1":"#1d2540","BG2":"#0c1326","TITLE_COLOR":"#F5F1E8","SUBTITLE_COLOR":"#E7DFCF","BADGE_BG":"#2A3358","BADGE_COLOR":"#F5F1E8"},
    "cool":   {"BG1":"#10222b","BG2":"#0a1720","TITLE_COLOR":"#EAF6FF","SUBTITLE_COLOR":"#D3EAF8","BADGE_BG":"#1c2f3a","BADGE_COLOR":"#EAF6FF"},
    "forest": {"BG1":"#142117","BG2":"#0b140d","TITLE_COLOR":"#F2F6EA","SUBTITLE_COLOR":"#E6EDD9","BADGE_BG":"#1c2b1f","BADGE_COLOR":"#F2F6EA"},
}

SVG_TEMPLATE = """\
<svg width="3000" height="3000" viewBox="0 0 3000 3000" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bggrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{{ BG1 }}"/>
      <stop offset="100%" stop-color="{{ BG2 }}"/>
    </linearGradient>
    <style>
      .title   { font: {{ TITLE_SIZE }}px sans-serif; fill: {{ TITLE_COLOR }}; font-weight: 700; }
      .subtitle{ font: {{ SUB_SIZE }}px  sans-serif; fill: {{ SUBTITLE_COLOR }}; opacity: 0.92; }
      .badge   { font: 64px  sans-serif; fill: {{ BADGE_COLOR }}; font-weight: 700; }
    </style>
  </defs>

  <rect x="0" y="0" width="3000" height="3000" fill="url(#bggrad)"/>

  {% if ART_PATH %}
  <image x="350" y="500" width="2300" height="1500"
         preserveAspectRatio="xMidYMid meet"
         href="{{ ART_PATH }}" xlink:href="{{ ART_PATH }}" opacity="0.96"/>
  {% endif %}

  <!-- Text block -->
  <g transform="translate(150, {{ TEXT_BASE_Y }})">
    {% if TITLE_LINES %}
    <text class="title">
      {% for line in TITLE_LINES -%}
        <tspan x="0" dy="{{ 0 if loop.first else TITLE_LINE_DY }}">{{ line }}</tspan>
      {%- endfor %}
    </text>
    {% endif %}

    {% if SUBTITLE_LINES %}
      <text class="subtitle" y="{{ SUBTITLE_OFFSET_Y }}">
        {% for line in SUBTITLE_LINES -%}
          <tspan x="0" dy="{{ 0 if loop.first else SUB_LINE_DY }}">{{ line }}</tspan>
        {%- endfor %}
      </text>
    {% endif %}
  </g>

  {% if BADGE %}
  <g transform="translate(150, 200)">
    <rect x="0" y="0" width="1200" height="150" rx="20" fill="{{ BADGE_BG }}" opacity="0.9"/>
    <text class="badge" x="40" y="100">{{ BADGE }}</text>
  </g>
  {% endif %}
</svg>
"""

# ---------- Helpers ----------
def humanize_safe_theme(s: str) -> str:
    base = s.replace("_", " ").replace("-", " ").strip()
    return " ".join(w.capitalize() for w in base.split())

def load_palette(palette_arg: str) -> dict:
    if not palette_arg:
        return PALETTES["warm"]
    if palette_arg.lower() in PALETTES:
        return PALETTES[palette_arg.lower()]
    p = Path(palette_arg)
    if p.exists():
        with p.open("r") as f:
            d = json.load(f)
        for k in ("BG1","BG2","TITLE_COLOR","SUBTITLE_COLOR","BADGE_BG","BADGE_COLOR"):
            if k not in d:
                raise ValueError(f"Palette JSON missing key: {k}")
        return d
    raise ValueError(f"Unknown palette: {palette_arg}")

def find_art(base: Path, safe: str, explicit_name: Optional[str]) -> Path:
    if explicit_name:
        cand = Path(explicit_name)
        if not cand.is_absolute():
            cand = base / explicit_name
        if cand.exists():
            return cand
        raise FileNotFoundError(f"Art not found: {cand}")
    # Try <safe>_art.*, then <safe>.*
    for pattern in (f"{safe}_art", f"{safe}"):
        for ext in ("png", "jpg", "jpeg", "webp"):
            cand = base / f"{pattern}.{ext}"
            if cand.exists():
                return cand
    raise FileNotFoundError(f"No art found in {base} for '{safe}' (expected '{safe}_art.(png|jpg|jpeg|webp)' or '{safe}.*')")

def upscale_to_3000(src: Path) -> Path:
    """Resize to 3000x3000 with LANCZOS + mild Unsharp; returns temp PNG if scaled, else original path."""
    with Image.open(src) as im:
        im = im.convert("RGBA")
        w, h = im.size
        if (w, h) == (3000, 3000):
            return src
        tmp = Path(tempfile.mkstemp(suffix=".png")[1])
        up = im.resize((3000, 3000), resample=Image.LANCZOS)
        up = up.filter(ImageFilter.UnsharpMask(radius=0.6, percent=60, threshold=2))
        up.save(tmp, "PNG")
        return tmp

def wrap_lines(text: str, width: int, max_lines: int) -> List[str]:
    """Soft wrap by words; trims to max_lines with ellipsis if needed."""
    if not text:
        return []
    lines = textwrap.wrap(text, width=width)
    if len(lines) > max_lines:
        keep = lines[:max_lines]
        # add ellipsis to last line if we trimmed content
        if len(" ".join(lines[max_lines-1:])) > 0:
            if len(keep[-1]) > 3:
                keep[-1] = keep[-1].rstrip(". ") + "…"
        return keep
    return lines

def svg_to_png(svg_bytes: bytes, out_png: Path):
    """Render SVG to PNG.
    Order: CairoSVG (python) -> Inkscape 1.x CLI -> Inkscape 0.92 legacy CLI -> rsvg-convert.
    Prints the CairoSVG error if it fails so we know why it fell back.
    """
    # 1) CairoSVG (preferred)
    try:
        import cairosvg
        cairosvg.svg2png(
            bytestring=svg_bytes,
            write_to=str(out_png),
            output_width=3000,
            output_height=3000
        )
        return
    except Exception as e:
        # Show why CairoSVG failed, then try CLIs
        print(f"⚠️  CairoSVG render failed: {e}", file=sys.stderr)

    # Write temp SVG for CLI renderers
    tmp_svg = Path(tempfile.mkstemp(suffix=".svg")[1])
    tmp_svg.write_bytes(svg_bytes)

    try:
        inkscape = shutil.which("inkscape")
        if inkscape:
            # 2) Inkscape 1.0+ (new CLI)
            try:
                subprocess.run(
                    [inkscape, str(tmp_svg),
                     "--export-type=png",
                     f"--export-filename={out_png}",
                     "--export-width=3000",
                     "--export-height=3000"],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                return
            except subprocess.CalledProcessError:
                # 3) Inkscape 0.92 (legacy CLI)
                subprocess.run(
                    [inkscape, str(tmp_svg),
                     f"--export-png={out_png}",
                     "-w", "3000", "-h", "3000"],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                return

        # 4) librsvg fallback
        rsvg = shutil.which("rsvg-convert")
        if rsvg:
            subprocess.run(
                [rsvg, "-w", "3000", "-h", "3000", "-o", str(out_png), str(tmp_svg)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return

        raise RuntimeError("No renderer available. Install 'cairosvg' (pip) or 'inkscape' or 'librsvg2-bin'.")
    finally:
        try: tmp_svg.unlink()
        except Exception: pass

def png_to_jpg(png_path: Path, jpg_path: Path, quality=92):
    with Image.open(png_path) as im:
        im = im.convert("RGB")
        im.save(jpg_path, "JPEG", quality=quality, optimize=True)

def embed_cover_in_mp3s(folder: Path, cover_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("⚠️  ffmpeg not found; skipping MP3 art embed.", file=sys.stderr)
        return
    mp3s = sorted(folder.glob("*.mp3"))
    if not mp3s:
        print("ℹ️  No MP3 files to tag in", folder)
        return
    for f in mp3s:
        tmp = f.with_name(f"_tmp_{f.name}")
        # Map audio from input, add cover as attached picture (JPEG), drop any existing pictures
        cmd = [
            ffmpeg, "-y",
            "-i", str(f),
            "-i", str(cover_path),
            "-map", "0:a", "-map", "1:v",
            "-c:a", "copy", "-c:v", "mjpeg",
            "-disposition:v", "attached_pic",
            str(tmp)
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            tmp.replace(f)
            print(f"🎵 Embedded cover into {f.name}")
        except subprocess.CalledProcessError:
            if tmp.exists():
                tmp.unlink()
            print(f"⚠️  Failed to embed cover into {f.name}", file=sys.stderr)

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(description="Build a story cover and optionally embed into MP3s.")
    ap.add_argument("safeTheme", help="safe theme slug (folder + filename base)")
    ap.add_argument("--title", default="", help="Cover title text; defaults to title-cased safeTheme")
    ap.add_argument("--subtitle", default="", help="Optional subtitle (e.g., 'Age 3–7 • Sharing ...')")
    ap.add_argument("--badge", default="", help="Optional badge (e.g., 'Includes 3 narrator voices')")
    ap.add_argument("--palette", default="warm", help="warm|cool|forest or /path/palette.json")
    ap.add_argument("--art", default="", help="Explicit art filename in base folder (or absolute path)")
    ap.add_argument("--base", default=DEFAULT_BASE, help=f"Base path (default {DEFAULT_BASE})")
    ap.add_argument("--out-name", default="", help="Override output filename (defaults to {safeTheme}_cover.jpg)")
    ap.add_argument("--no-embed", action="store_true", help="Skip embedding cover.jpg into MP3s")
    # advanced text fitting
    ap.add_argument("--title-width", type=int, default=22, help="Approx chars per title line (wrap)")
    ap.add_argument("--title-lines", type=int, default=2, help="Max title lines")
    ap.add_argument("--subtitle-width", type=int, default=38, help="Approx chars per subtitle line (wrap)")
    ap.add_argument("--subtitle-lines", type=int, default=2, help="Max subtitle lines")
    args = ap.parse_args()

    base = Path(args.base).resolve()
    safe = args.safeTheme
    outdir = base / safe
    outdir.mkdir(parents=True, exist_ok=True)
    out_name = args.out_name or f"{safe}_cover.jpg"
    out_path = outdir / out_name

    # Palette
    pal = load_palette(args.palette)

    # Title/Subtitle
    title = args.title.strip() or humanize_safe_theme(safe)
    subtitle = args.subtitle.strip()
    title_lines = wrap_lines(title, width=args.title_width, max_lines=args.title_lines)
    subtitle_lines = wrap_lines(subtitle, width=args.subtitle_width, max_lines=args.subtitle_lines)

    # Basic font sizes (shrink title a bit if multi-line)
    TITLE_SIZE = 140 if len(title_lines) == 1 else 120
    SUB_SIZE = 80

    # Y positioning: if title has extra lines, lift block a touch
    TEXT_BASE_Y = 2150 - (0 if len(title_lines) == 1 else 40)
    TITLE_LINE_DY = 150
    SUB_LINE_DY = 100
    SUBTITLE_OFFSET_Y = 160 + (TITLE_LINE_DY * (len(title_lines)-1 if len(title_lines)>0 else 0))

    # Art
    art_src = find_art(base, safe, args.art or None)
    art_norm = upscale_to_3000(art_src)

    # Render SVG
    svg = Template(SVG_TEMPLATE).render(
        ART_PATH=str(art_norm),
        TITLE_LINES=title_lines,
        SUBTITLE_LINES=subtitle_lines,
        BADGE=args.badge.strip(),
        TEXT_BASE_Y=TEXT_BASE_Y,
        TITLE_LINE_DY=TITLE_LINE_DY,
        SUB_LINE_DY=SUB_LINE_DY,
        SUBTITLE_OFFSET_Y=SUBTITLE_OFFSET_Y,
        TITLE_SIZE=TITLE_SIZE,
        SUB_SIZE=SUB_SIZE,
        **pal,
    ).encode("utf-8")

    # SVG -> PNG -> JPG
    tmp_png = Path(tempfile.mkstemp(suffix=".png")[1])
    try:
        svg_to_png(svg, tmp_png)
        png_to_jpg(tmp_png, out_path, quality=92)
    finally:
        try: tmp_png.unlink()
        except Exception: pass
        if art_norm != art_src:
            try: Path(art_norm).unlink()
            except Exception: pass

    print(f"✅ Cover written: {out_path}")

    # Embed into MP3s
    if not args.no_embed:
        embed_cover_in_mp3s(outdir, out_path)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
