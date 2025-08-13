# BedtimeStory_Coverbuilder

Build polished **3000×3000 audiobook covers** from your AI artwork and story metadata — then **embed** the cover into your MP3s and **zip** the finished bundle for upload (Etsy, Audiobooks.com, etc.).

This tool is designed to fit into an automated pipeline (e.g., n8n). It is **CPU‑friendly** and works fully offline.

---

## Features

- ✅ **Cover composer (3000×3000 JPG)**  
  Gradient background + your art + title/subtitle + optional badge.
- ✅ **Robust SVG rendering**  
  Uses CairoSVG when available; falls back to Inkscape or rsvg-convert. Artwork is embedded as a **base64 data URI** to avoid path/URI issues.
- ✅ **MP3 tagging**  
  Embeds the finished cover as attached picture into all `.mp3` files in the story folder using `ffmpeg` (lossless audio copy).
- ✅ **Bundling**  
  Zips the **story folder** contents into `{safe}.zip` and places it **inside** that folder.
- ✅ **Non-destructive & safe deletes**  
  Deletes only the original art file **if it lives under the base folder**; temporary files are cleaned up.

---

## Requirements

### System
- **Python 3.8+**
- **ffmpeg** (for MP3 cover embedding)
- (Optional render fallbacks): **Inkscape** or **librsvg2-bin**

On Debian/Ubuntu:
```bash
sudo apt-get update
sudo apt-get install -y ffmpeg inkscape librsvg2-bin \
    libcairo2 libpango-1.0-0 libgdk-pixbuf2.0-0 fonts-dejavu-core
```

> CairoSVG uses the cairo/pango stack. The packages above ensure robust font rendering.

### Python (venv recommended)

```bash
cd ~/BedtimeStory_Coverbuilder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` includes:
- `Jinja2` – templating
- `Pillow` – image I/O/conversion
- `CairoSVG` – fast, local SVG → PNG (optional but preferred)

---

## Directory layout & inputs

- **Base folder (default):** `/mnt/ai_data/BedtimeStories`
- **Story folder:** `{base}/{safeTheme}` (created automatically)
- **Expected art filename:** one of
  - `{base}/{safeTheme}_art.(png|jpg|jpeg|webp)` **or**
  - `{base}/{safeTheme}.(png|jpg|jpeg|webp)`
  - or pass `--art <filename>`

All **`.mp3`** files found in `{base}/{safeTheme}` will receive the embedded cover (unless `--no-embed`).

---

## Usage

```bash
./build_cover.py <safeTheme> \
  --subtitle "Age 3–7 • Sharing makes everyone feel safe and happy" \
  --badge "3 Narrator Voices" \
  --palette warm \
  --art <safeTheme>.png \
  --out-name <safeTheme>_cover.jpg
```

- `<safeTheme>`: slug used for the folder and filenames (e.g., `friendly_dinosaurs`).
- `--title`: optional; defaults to title‑cased `<safeTheme>`.
- `--subtitle`: optional text under the title (e.g., age range + moral).
- `--badge`: optional pill at the top-left (e.g., `3 Narrator Voices`).
- `--palette`: one of `warm|cool|forest` or a path to a custom JSON palette:
  ```json
  { "BG1":"#1d2540","BG2":"#0c1326","TITLE_COLOR":"#F5F1E8",
    "SUBTITLE_COLOR":"#E7DFCF","BADGE_BG":"#2A3358","BADGE_COLOR":"#F5F1E8" }
  ```
- `--art`: explicit art filename (in base or absolute path). If omitted, the script looks for standard names as above.
- `--base`: override base folder (default `/mnt/ai_data/BedtimeStories`).
- `--out-name`: override output cover filename (default `{safeTheme}_cover.jpg`).
- `--no-embed`: skip embedding the cover into MP3s.

### What happens on run
1. Find and normalize art → **3000×3000** (CPU, Pillow).  
2. Compose SVG (art embedded as **data URI**) → render PNG/JPG.  
3. Write `{base}/{safeTheme}/{safeTheme}_cover.jpg`.  
4. Embed cover into any `.mp3` files in the story folder (unless `--no-embed`).  
5. **Delete** the original art in the base folder (safe only if inside base).  
6. Create `{base}/{safeTheme}/{safeTheme}.zip` containing the story folder contents.

---

## Examples

### Local run
```bash
# Activate venv
source ~/BedtimeStory_Coverbuilder/.venv/bin/activate

# Build cover, embed, zip
./build_cover.py friendship_among_forest_animals \
  --subtitle "Age 3–7 • Often slow and steady wins the race" \
  --badge "3 Narrator Voices" \
  --palette warm \
  --art friendship_among_forest_animals.png \
  --out-name friendship_among_forest_animals_cover.jpg
```

### n8n / remote (Execute Command via SSH)
Use a single-quoted SSH command, ensure UTF‑8 locale, and quote dynamic args:
```bash
ssh user@host 'LC_ALL=C.UTF-8 /path/to/.venv/bin/python /path/to/build_cover.py {{ $("Story Setup").item.json.safeTheme }} --subtitle "Age 3–7 • {{ $("Get Random Story Seed").item.json.moral.replace(/\"/g, "\\\"") }}" --badge "3 Narrator Voices" --palette warm --art "{{ $("Story Setup").item.json.safeTheme }}.png" --out-name "{{ $("Story Setup").item.json.safeTheme }}_cover.jpg"'
```

---

## Troubleshooting

- **Cover renders but artwork missing**  
  Fixed: artwork is now **embedded** as a base64 data URI, so renderers don’t need to resolve paths or URIs.

- **CairoSVG errors (fonts/cairo/pango)**  
  Install: `libcairo2 libpango-1.0-0 libgdk-pixbuf2.0-0 librsvg2-2 fonts-dejavu-core`

- **No MP3s found / cover not embedded**  
  Ensure your `.mp3` files live in `{base}/{safeTheme}`. The script writes the cover first, then tags all MP3s it finds.

- **ZIP includes itself**  
  The script builds the ZIP in a temp folder and moves it into the story folder at the end — so no self-inclusion.

---

## Development notes

- The script deletes the **source art** only if it resides **under the base folder**. Absolute paths or files outside base are left untouched.
- Artwork is normalized to 3000×3000 using Pillow (LANCZOS + mild sharpening). If input is already 3000×3000, it is used as-is.
- If CairoSVG is unavailable, the script falls back to Inkscape (any version) or `rsvg-convert`.

---

## License

MIT (or your preferred license here)
