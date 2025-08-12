#!/bin/bash
# prep_story_assets.sh
# Usage: ./prep_story_assets.sh <safeTheme>
# Env:
#   STORY_BASE=/custom/path    # default: /mnt/ai_data/BedtimeStories
#   STEREO=1                   # set for dual-channel output; default mono

set -euo pipefail

BASE="${STORY_BASE:-/mnt/ai_data/BedtimeStories}"

if [[ $# -lt 1 || -z "${1:-}" ]]; then
  echo "❌ Usage: $0 <safeTheme>"
  exit 1
fi

SAFE_THEME="$1"
STORY_DIR="${BASE}/${SAFE_THEME}"

command -v ffmpeg >/dev/null 2>&1 || { echo "❌ ffmpeg not found. sudo apt install ffmpeg"; exit 1; }

mkdir -p "$BASE" "$STORY_DIR"

# audio export settings
BITRATE="192k"
RATE="44100"
CHANNELS="${STEREO:-}" && CHANNELS=$([[ "$CHANNELS" == "1" ]] && echo 2 || echo 1)  # default 1ch; STEREO=1 -> 2ch
[[ "${STEREO:-}" == "1" ]] && CHANNELS=2 || CHANNELS=1

echo "📁 Base:  $BASE"
echo "📁 Story: $STORY_DIR"
echo "🎚️  MP3:  ${CHANNELS}ch @ ${RATE} Hz, ${BITRATE}"

# ---------- voice label mapping ----------
label_for_voice() {
  local tag="$1"
  # normalize tag a bit (strip spaces)
  tag="${tag// /}"
  case "$tag" in
    af_nicole)   echo "Gentle_Feminine" ;;
    bm_lewis)    echo "Warm_Adult" ;;
    am_michael)  echo "Neutral_Storyteller" ;;
    # If you add more mappings, extend here:
    # af_bella)    echo "Gentle_Feminine_Bella" ;;
    # bm_george)   echo "Warm_Adult_Deep" ;;
    *)
      # fallback: keep the tag (sanitized) so it’s still identifiable
      echo "$tag"
      ;;
  esac
}

# ---------- convert WAV -> MP3 with friendly names ----------
shopt -s nullglob
WAVS=( "${BASE}/${SAFE_THEME}"*.wav )

if (( ${#WAVS[@]} == 0 )); then
  echo "⚠️  No WAVs found matching '${SAFE_THEME}*.wav' in ${BASE}"
else
  echo "🎧 Converting ${#WAVS[@]} WAV file(s) to MP3 with friendly labels..."
  for wav in "${WAVS[@]}"; do
    bn="$(basename "$wav" .wav)"          # e.g., friendly_dinosaurs_af_nicole
    voice_tag="$bn"

    # Try to extract the voice tag after the safeTheme prefix (handles _, -, or space as separator)
    if [[ "$voice_tag" == "${SAFE_THEME}"* ]]; then
      voice_tag="${voice_tag#${SAFE_THEME}}"   # remove prefix
      voice_tag="${voice_tag#[ _-]}"          # drop one leading separator if present
    fi

    # Map to friendly label (or keep tag if unknown)
    label="$(label_for_voice "$voice_tag")"
    out="${STORY_DIR}/${SAFE_THEME} - ${label}.mp3"

    echo "  • $(basename "$wav") -> $(basename "$out")"
    ffmpeg -y -loglevel error -i "$wav" -ac "$CHANNELS" -ar "$RATE" -b:a "$BITRATE" "$out"
  done
fi

# ---------- move/copy narration texts ----------
SSML_SRC="${BASE}/${SAFE_THEME}_narration.txt"
if [[ -f "$SSML_SRC" ]]; then
  SSML_DST="${STORY_DIR}/${SAFE_THEME}_narration.txt"
  PLAIN_DST="${STORY_DIR}/${SAFE_THEME}_narration_plain.txt"

  echo "📝 Moving SSML narration to: $(basename "$SSML_DST")"
  cp -f "$SSML_SRC" "$SSML_DST"

  echo "🧹 Generating plain text (strip SSML tags) -> $(basename "$PLAIN_DST")"
  sed -E \
    -e 's/\r//g' \
    -e 's:<speak[^>]*>::gi' \
    -e 's:</speak>::gi' \
    -e 's:<break[^>]*1\.2s[^>]*/>:\n\n:gi' \
    -e 's:<break[^>]*400ms[^>]*/>:\n:gi' \
    -e 's:<break[^>]*/>:\n:gi' \
    -e 's:<[^>]+>::g' \
    "$SSML_SRC" \
  | awk '
      { gsub(/[ \t]+$/, ""); }
      NF==0 { blanks++; if (blanks<3) print ""; next }
      { blanks=0; print }
    ' \
  | sed -E 's/[ \t]+/ /g' > "$PLAIN_DST"

  rm -f "$SSML_SRC"
else
  echo "⚠️  No narration file found: ${SSML_SRC}"
fi

# ---------- cleanup original WAVs in base ----------
if (( ${#WAVS[@]} > 0 )); then
  echo "🧽 Deleting original WAVs from base..."
  rm -f "${WAVS[@]}"
fi

echo "✅ Done."
echo "📦 Ready: ${STORY_DIR}"
echo "   Contains:"
echo "     • MP3(s): ${SAFE_THEME} - Warm_Adult.mp3, Gentle_Feminine.mp3, Neutral_Storyteller.mp3 (etc.)"
echo "     • ${SAFE_THEME}_narration.txt (SSML)"
echo "     • ${SAFE_THEME}_narration_plain.txt (clean text)"
