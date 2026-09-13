# media-subtitle-pipeline

[![Platform: macOS / Linux](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey.svg)](https://apple.com/macos)
[![Python: 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://python.org)
[![Tested with Pytest](https://img.shields.io/badge/Tests-133%20passed-brightgreen.svg)]()
[![Engine Version](https://img.shields.io/badge/Version-2.3.1-informational.svg)]()

An AI-assisted personal workflow for subtitle translation, context management, validation, and media delivery. Engineered specifically for pairing with autonomous AI coding agents (Antigravity / Codex) and multi-agent workflows.

> **Project & Development Note**  
> This project is a personal AI-assisted workflow tool designed and iterated by **Abdulaziz Kiran**. The personal contribution focused on defining the real-world media problem, structuring the end-to-end workflow, specifying requirements and format edge cases, establishing validation criteria, and iteratively testing, identifying failures, and guiding fixes across iterations. Implementation and debugging were carried out with substantial assistance from AI coding agents. While automated tests verify defined behavior under tested constraints, this project represents an experimental personal workflow rather than a production enterprise deployment.

---

## 🌟 Highlights & Architecture

```text
Source Media (.mkv / .mp4 / .ass)
   │
   ├── 1. Stream Extraction & Audio Identification (FFmpeg / FFprobe)
   │       └── Auto-detects original audio (e.g. Japanese track priority for anime)
   │
   ├── 2. Cryptographic Series Context (series_context.py)
   │       └── Immutable, hash-chained ledger for characters, relations, terms
   │
   ├── 3. Job Partitioning & Request Batching (run_pipeline.py prepare)
   │       └── Splits dialogue into bounded batches with strict slot boundaries
   │
   ├── 4. Autonomous Agent Translation & Double-Blind Review
   │       └── Independent translator & reviewer passes with full schema validation
   │
   ├── 5. Subtitle Core & Verification Engine (subtitle_core.py, verify_integrity.py)
   │       ├── Strict ASS/SSA syntax & CPS limit checks
   │       ├── Karaoke tag reset isolation (\k, \K, \kf, \ko)
   │       └── Slot modification and alpha injection prevention
   │
   ├── 6. Visual QA & Font Inspection (verify_render_qa.py, install_original_fonts.py)
   │       ├── Targeted libass frame renders for collision/overlap checks
   │       └── Font family & weight validation from true OpenType metadata tables
   │
   ├── 7. Lossless Content Cut & Muxing (content_filter_pipeline.py, mux_mkv.py)
   │       ├── Keyframe-aligned trimming with H.264/H.265 open-GOP fallback
   │       └── Muxes translated ASS, verified fonts, and preserved audio tracks
   │
   └── 8. Immutable Central Delivery & CEFR Learning Report (archive_delivery.py)
           └── SHA-256 verified bundle archive with atomic failure rollback
```

---

## 🛠️ Key Capabilities

- **Strict ASS / SSA Format Enforcement**: Validates tag syntax, prevents unescaped newlines, preserves formatting tags while isolating translated text spans.
- **Karaoke & Song Pipeline**: Handles dual-track song lines (Romaji + Turkish translation) with tag isolation and resets (`{\kt0\k0}{\r}\N`).
- **Cryptographic State & Resume**: Every pipeline stage (`prepare`, `translation`, `review`, `build`, `finalize`) verifies cryptographic input/output hashes. Interrupted jobs resume without duplicate work.
- **Series Consistency Engine**: Multi-episode anime and drama context manager (`series_context.py`) tracks entities, honorifics, and terminology across episodes with append-only revisions.
- **Grounded English Learning Reports**: Generates CEFR-anchored vocabulary and comprehension dossiers directly linked to line timestamps and verified dialogue text.
- **Lossless Cutting & Keyframe Alignment**: Media trimming tool (`content_filter_pipeline.py`) segments along keyframes, handles B-frames, and provides lossless re-encoding fallbacks with full evidence bundles.

---

## 🧪 Verification & Test Suite

The pipeline is verified by a suite of **133 unit and integration tests**, challenging boundaries including:
- Malformed subtitle strings and injection attacks
- Karaoke tag resets and multi-part line preservation
- Stale review detection upon source or context modification
- OpenType font table parsing and spoofing prevention
- H.264 B-frame and H.265 open-GOP cut integrity
- Transactional rollback on delivery failure

Run tests locally:

```bash
# Using uv (recommended)
uv run pytest -v

# Or using python unittest
python3 -m unittest discover -s tests -v
```

---

## 🚀 Quickstart

### Prerequisites
- Python 3.12+
- `uv` (recommended) or `pip`
- `ffmpeg` and `ffprobe` (libass enabled for visual QA rendering)

### Installation
```bash
git clone https://github.com/Abdulaziz-kiran/media-subtitle-pipeline.git
cd media-subtitle-pipeline
uv sync --extra dev
```

### Basic Workflow
```bash
# 1. Prepare job folder from an ASS subtitle file
uv run python3 scripts/run_pipeline.py prepare /path/to/source.ass jobs/episode-01

# 2. Check stage status and receipts
uv run python3 scripts/run_pipeline.py status --job jobs/episode-01
uv run python3 scripts/run_pipeline.py receipt --job jobs/episode-01 --stage translation

# 3. Build candidate ASS after translation
uv run python3 scripts/run_pipeline.py build --job jobs/episode-01

# 4. Finalize and archive
uv run python3 scripts/run_pipeline.py finalize --job jobs/episode-01
```

---

## 📄 License & Attribution

Project design, requirements, and specifications by **Abdulaziz Kiran** (AI-assisted implementation). Designed for integration with Antigravity / Codex AI agent workspaces.
Bundled OpenType fonts (`Source Sans 3`) are distributed under the SIL Open Font License (OFL).
