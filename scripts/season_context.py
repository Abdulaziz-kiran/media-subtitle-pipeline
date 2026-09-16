#!/usr/bin/env python3
"""Prepare and validate season-wide source context, then derive spoiler-safe episode views.

The season context is immutable source analysis. It is distinct from the
hash-chained series_context ledger, which stores reviewed Turkish translation
decisions accumulated after episode finalization.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import unicodedata

import pysubs2

from subtitle_core import file_hash, read_json, write_json, visible, role

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
SHA256 = re.compile(r"[0-9a-f]{64}")
STATUSES = {"verified", "single_stream", "unknown", "not_applicable"}
TERM_STATES = {"locked", "preferred", "tentative"}
UNCERTAINTY_STATUSES = {"open", "resolved"}
GUARDRAIL_RULES = {
    "preserve_ambiguity", "preserve_identity_uncertainty", "preserve_gender_uncertainty",
    "preserve_relationship_uncertainty", "do_not_explain", "terminology", "register", "other",
}
RECURRING_TYPES = {"running_joke", "catchphrase", "callback", "motif", "nickname", "wordplay", "other"}
CONTENT_FILTER_CATEGORIES = {"kissing", "sexual_intimacy", "intimate_bed_scene"}


def text(value, label, minimum=0, maximum=2000, *, required=False):
    if not isinstance(value, str):
        raise ValueError(label + " must be text")
    value = unicodedata.normalize("NFC", value).strip()
    if required and not value:
        raise ValueError(label + " is required")
    if not minimum <= len(value) <= maximum or "\x00" in value:
        raise ValueError(label + " has invalid length")
    return value


def identifier(value, label):
    value = text(value, label, 1, 100, required=True)
    if not ID.fullmatch(value):
        raise ValueError(label + " is not a safe identifier")
    return value


def line_ids(value, label="line_indices"):
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError(label + " must be a bounded list")
    if any(type(v) is not int or v < 0 for v in value) or len(value) != len(set(value)):
        raise ValueError(label + " contains invalid line ids")
    return value


def evidence_rows(value, episode_map):
    if not isinstance(value, list) or not value or len(value) > 100:
        raise ValueError("Evidence must be a non-empty bounded list")
    for row in value:
        if not isinstance(row, dict) or set(row) != {"episode_id", "source_sha256", "line_indices"}:
            raise ValueError("Invalid season evidence row")
        episode = identifier(row["episode_id"], "evidence episode_id")
        if episode not in episode_map:
            raise ValueError("Evidence references an episode outside season coverage")
        if row["source_sha256"] != episode_map[episode]["source_sha256"]:
            raise ValueError("Evidence source hash does not match the season source")
        line_ids(row["line_indices"])


def optional_window(entry, order, label):
    start = entry.get("valid_from")
    end = entry.get("valid_through")
    if start is not None:
        identifier(start, label + " valid_from")
        if start not in order:
            raise ValueError(label + " valid_from is outside coverage")
    if end is not None:
        identifier(end, label + " valid_through")
        if end not in order:
            raise ValueError(label + " valid_through is outside coverage")
    if start is not None and end is not None and order[start] > order[end]:
        raise ValueError(label + " validity window is reversed")


def active(entry, episode_id, order):
    idx = order[episode_id]
    start = entry.get("valid_from")
    end = entry.get("valid_through")
    return (start is None or order[start] <= idx) and (end is None or idx <= order[end])


def validate_season_context(data):
    expected = {
        "schema_version", "series_id", "season_id", "title", "media_type", "source_language", "target_language",
        "original_audio_language", "original_audio_status", "original_audio_evidence", "episode_sources",
        "characters", "relationships", "voices", "glossary", "recurring_elements", "episode_notes",
        "guardrails", "uncertainties", "content_filter_candidates",
    }
    if not isinstance(data, dict):
        raise ValueError("Invalid season context fields")
    # 2.4.0 contexts remain readable; new contexts always write the candidate list.
    if set(data) == expected - {"content_filter_candidates"}:
        data = dict(data); data["content_filter_candidates"] = []
    elif set(data) != expected:
        raise ValueError("Invalid season context fields")
    if data["schema_version"] != 1:
        raise ValueError("Unsupported season context version")
    if len(json.dumps(data, ensure_ascii=False)) > 4_000_000:
        raise ValueError("Season context is too large")
    identifier(data["series_id"], "series_id")
    identifier(data["season_id"], "season_id")
    text(data["title"], "title", 1, 200, required=True)
    text(data["media_type"], "media_type", 1, 50, required=True)
    text(data["source_language"], "source_language", 1, 32, required=True)
    text(data["target_language"], "target_language", 1, 32, required=True)
    status = data["original_audio_status"]
    if status not in STATUSES:
        raise ValueError("Invalid original_audio_status")
    text(data["original_audio_language"], "original_audio_language", 0, 32)
    text(data["original_audio_evidence"], "original_audio_evidence", 0, 1000)
    if status in {"verified", "single_stream"}:
        if not data["original_audio_language"].strip() or len(data["original_audio_evidence"].strip()) < 10:
            raise ValueError("Verified original audio requires language and evidence")
    elif data["original_audio_language"]:
        raise ValueError("Unverified original audio cannot name a language")

    sources = data["episode_sources"]
    if not isinstance(sources, list) or not sources or len(sources) > 500:
        raise ValueError("episode_sources must be a non-empty bounded list")
    episode_map = {}
    for row in sources:
        if not isinstance(row, dict) or set(row) != {"episode_id", "source_sha256", "source_file"}:
            raise ValueError("Invalid episode source")
        ep = identifier(row["episode_id"], "episode_id")
        if ep in episode_map:
            raise ValueError("Duplicate episode_id")
        if not isinstance(row["source_sha256"], str) or not SHA256.fullmatch(row["source_sha256"]):
            raise ValueError("Episode source needs a SHA-256")
        text(row["source_file"], "source_file", 1, 1000, required=True)
        episode_map[ep] = row
    order = {ep: i for i, ep in enumerate(episode_map)}

    characters = data["characters"]
    if not isinstance(characters, dict) or len(characters) > 1000:
        raise ValueError("characters must be a bounded object")
    for cid, row in characters.items():
        identifier(cid, "character id")
        if not isinstance(row, dict) or set(row) != {"name", "aliases", "translation_guidance", "visible_from", "evidence"}:
            raise ValueError("Invalid character entry")
        text(row["name"], "character name", 1, 200, required=True)
        if not isinstance(row["aliases"], list) or len(row["aliases"]) > 50:
            raise ValueError("Character aliases must be bounded")
        for alias in row["aliases"]:
            text(alias, "character alias", 1, 200, required=True)
        text(row["translation_guidance"], "character translation_guidance", 0, 1000)
        if row["visible_from"] is not None and row["visible_from"] not in order:
            raise ValueError("Character visible_from is outside coverage")
        evidence_rows(row["evidence"], episode_map)

    relationships = data["relationships"]
    if not isinstance(relationships, list) or len(relationships) > 5000:
        raise ValueError("relationships must be a bounded list")
    rel_ids = set()
    for row in relationships:
        required = {"id", "from_character", "to_character", "description", "address_forms", "translation_guidance", "valid_from", "valid_through", "evidence"}
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("Invalid relationship entry")
        rid = identifier(row["id"], "relationship id")
        if rid in rel_ids:
            raise ValueError("Duplicate relationship id")
        rel_ids.add(rid)
        if row["from_character"] not in characters or row["to_character"] not in characters:
            raise ValueError("Relationship references unknown character")
        text(row["description"], "relationship description", 1, 500, required=True)
        if not isinstance(row["address_forms"], list) or len(row["address_forms"]) > 50:
            raise ValueError("address_forms must be bounded")
        for form in row["address_forms"]:
            text(form, "address form", 1, 160, required=True)
        text(row["translation_guidance"], "relationship translation_guidance", 0, 1000)
        optional_window(row, order, "relationship")
        evidence_rows(row["evidence"], episode_map)

    voices = data["voices"]
    if not isinstance(voices, dict) or len(voices) > 1000:
        raise ValueError("voices must be a bounded object")
    for cid, row in voices.items():
        if cid not in characters:
            raise ValueError("Voice references unknown character")
        if not isinstance(row, dict) or set(row) != {"guidance", "valid_from", "valid_through", "evidence"}:
            raise ValueError("Invalid voice entry")
        text(row["guidance"], "voice guidance", 1, 1000, required=True)
        optional_window(row, order, "voice")
        evidence_rows(row["evidence"], episode_map)

    glossary = data["glossary"]
    if not isinstance(glossary, dict) or len(glossary) > 5000:
        raise ValueError("glossary must be a bounded object")
    for key, row in glossary.items():
        identifier(key, "glossary id")
        if not isinstance(row, dict) or set(row) != {"source", "preferred_tr", "aliases", "note", "state", "valid_from", "valid_through", "evidence"}:
            raise ValueError("Invalid glossary entry")
        text(row["source"], "glossary source", 1, 300, required=True)
        text(row["preferred_tr"], "glossary preferred_tr", 1, 300, required=True)
        if not isinstance(row["aliases"], list) or len(row["aliases"]) > 50:
            raise ValueError("Glossary aliases must be bounded")
        for alias in row["aliases"]:
            text(alias, "glossary alias", 1, 300, required=True)
        text(row["note"], "glossary note", 0, 1000)
        if row["state"] not in TERM_STATES:
            raise ValueError("Invalid glossary state")
        optional_window(row, order, "glossary")
        evidence_rows(row["evidence"], episode_map)

    recurring = data["recurring_elements"]
    if not isinstance(recurring, list) or len(recurring) > 2000:
        raise ValueError("recurring_elements must be a bounded list")
    recurring_ids = set()
    for row in recurring:
        if not isinstance(row, dict) or set(row) != {"id", "type", "description", "translation_guidance", "occurrences"}:
            raise ValueError("Invalid recurring element")
        rid = identifier(row["id"], "recurring id")
        if rid in recurring_ids:
            raise ValueError("Duplicate recurring id")
        recurring_ids.add(rid)
        if row["type"] not in RECURRING_TYPES:
            raise ValueError("Invalid recurring element type")
        text(row["description"], "recurring description", 1, 1000, required=True)
        text(row["translation_guidance"], "recurring translation_guidance", 0, 1000)
        if not isinstance(row["occurrences"], list) or not row["occurrences"] or len(row["occurrences"]) > 500:
            raise ValueError("Recurring occurrences must be a non-empty bounded list")
        for occ in row["occurrences"]:
            if not isinstance(occ, dict) or set(occ) != {"episode_id", "line_indices"} or occ["episode_id"] not in order:
                raise ValueError("Invalid recurring occurrence")
            line_ids(occ["line_indices"])

    notes = data["episode_notes"]
    if not isinstance(notes, dict) or set(notes) - set(order):
        raise ValueError("episode_notes contains unknown episodes")
    for ep, row in notes.items():
        if not isinstance(row, dict) or set(row) != {"translation_summary", "notes", "songs"}:
            raise ValueError("Invalid episode note")
        text(row["translation_summary"], "episode translation_summary", 0, 2000)
        if not isinstance(row["notes"], list) or len(row["notes"]) > 500:
            raise ValueError("Episode notes must be bounded")
        for note in row["notes"]:
            if not isinstance(note, dict) or set(note) != {"kind", "line_indices", "instruction", "reference_episode"}:
                raise ValueError("Invalid episode note item")
            text(note["kind"], "episode note kind", 1, 100, required=True)
            line_ids(note["line_indices"])
            text(note["instruction"], "episode note instruction", 1, 1000, required=True)
            ref = note["reference_episode"]
            if ref is not None:
                if ref not in order:
                    raise ValueError("Episode note references unknown episode")
                if order[ref] > order[ep]:
                    raise ValueError("Episode note cannot expose a future episode; use a guardrail instead")
        if not isinstance(row["songs"], list) or len(row["songs"]) > 100:
            raise ValueError("Episode songs must be bounded")
        for song in row["songs"]:
            if not isinstance(song, dict) or set(song) != {"line_indices", "note"}:
                raise ValueError("Invalid episode song")
            line_ids(song["line_indices"])
            text(song["note"], "song note", 1, 1000, required=True)

    guardrails = data["guardrails"]
    if not isinstance(guardrails, list) or len(guardrails) > 5000:
        raise ValueError("guardrails must be a bounded list")
    for row in guardrails:
        if not isinstance(row, dict) or set(row) != {"episode_id", "line_indices", "rule", "instruction", "evidence"}:
            raise ValueError("Invalid guardrail")
        if row["episode_id"] not in order:
            raise ValueError("Guardrail references unknown episode")
        line_ids(row["line_indices"])
        if row["rule"] not in GUARDRAIL_RULES:
            raise ValueError("Invalid guardrail rule")
        text(row["instruction"], "guardrail instruction", 1, 1000, required=True)
        evidence_rows(row["evidence"], episode_map)

    candidates = data["content_filter_candidates"]
    if not isinstance(candidates, list) or len(candidates) > 5000:
        raise ValueError("content_filter_candidates must be a bounded list")
    candidate_ids = set()
    for row in candidates:
        required = {"id", "episode_id", "line_indices", "category", "reason", "evidence"}
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("Invalid content filter candidate")
        cid = identifier(row["id"], "content filter candidate id")
        if cid in candidate_ids:
            raise ValueError("Duplicate content filter candidate id")
        candidate_ids.add(cid)
        if row["episode_id"] not in order:
            raise ValueError("Content filter candidate references unknown episode")
        line_ids(row["line_indices"], "content filter line_indices")
        if row["category"] not in CONTENT_FILTER_CATEGORIES:
            raise ValueError("Invalid content filter category")
        text(row["reason"], "content filter reason", 1, 1000, required=True)
        evidence_rows(row["evidence"], episode_map)

    uncertainties = data["uncertainties"]
    if not isinstance(uncertainties, list) or len(uncertainties) > 5000:
        raise ValueError("uncertainties must be a bounded list")
    uncertainty_ids = set()
    for row in uncertainties:
        if not isinstance(row, dict) or set(row) != {"id", "episode_id", "line_indices", "question", "translation_instruction", "status", "resolution", "evidence"}:
            raise ValueError("Invalid uncertainty")
        uid = identifier(row["id"], "uncertainty id")
        if uid in uncertainty_ids:
            raise ValueError("Duplicate uncertainty id")
        uncertainty_ids.add(uid)
        if row["episode_id"] not in order:
            raise ValueError("Uncertainty references unknown episode")
        line_ids(row["line_indices"])
        text(row["question"], "uncertainty question", 1, 1000, required=True)
        text(row["translation_instruction"], "uncertainty translation_instruction", 1, 1000, required=True)
        if row["status"] not in UNCERTAINTY_STATUSES:
            raise ValueError("Invalid uncertainty status")
        text(row["resolution"], "uncertainty resolution", 0, 1000)
        if row["status"] == "resolved" and not row["resolution"].strip():
            raise ValueError("Resolved uncertainty needs a resolution")
        evidence_rows(row["evidence"], episode_map)
    return data


def validate_manifest(data):
    expected = {"schema_version", "series_id", "season_id", "title", "media_type", "source_language", "target_language",
                "original_audio_language", "original_audio_status", "original_audio_evidence", "episodes"}
    if not isinstance(data, dict) or set(data) != expected or data["schema_version"] != 1:
        raise ValueError("Invalid season manifest")
    identifier(data["series_id"], "series_id"); identifier(data["season_id"], "season_id")
    text(data["title"], "title", 1, 200, required=True); text(data["media_type"], "media_type", 1, 50, required=True)
    text(data["source_language"], "source_language", 1, 32, required=True); text(data["target_language"], "target_language", 1, 32, required=True)
    if data["original_audio_status"] not in STATUSES:
        raise ValueError("Invalid original_audio_status")
    text(data["original_audio_language"], "original_audio_language", 0, 32)
    text(data["original_audio_evidence"], "original_audio_evidence", 0, 1000)
    if not isinstance(data["episodes"], list) or not data["episodes"] or len(data["episodes"]) > 500:
        raise ValueError("Season manifest needs episodes")
    seen = set()
    for row in data["episodes"]:
        if not isinstance(row, dict) or set(row) != {"episode_id", "subtitle"}:
            raise ValueError("Invalid season manifest episode")
        ep = identifier(row["episode_id"], "episode_id")
        if ep in seen:
            raise ValueError("Duplicate episode_id")
        seen.add(ep)
        p = Path(text(row["subtitle"], "subtitle path", 1, 2000, required=True)).expanduser()
        if not p.is_file():
            raise ValueError("Subtitle file not found: " + str(p))
    return data


def prepare_reading_pack(manifest_path, output_path):
    manifest_path = Path(manifest_path).resolve()
    data = validate_manifest(read_json(manifest_path))
    episodes = []
    for row in data["episodes"]:
        path = Path(row["subtitle"]).expanduser().resolve()
        subs = pysubs2.load(path)
        lines = []
        for idx, event in enumerate(subs):
            kind = role(event)
            rendered = visible(event.text).strip()
            if kind in {"comment", "drawing", "empty"} or not rendered:
                continue
            lines.append({
                "id": idx,
                "start_ms": int(event.start),
                "end_ms": int(event.end),
                "kind": kind,
                "speaker": (event.name or "").strip(),
                "style": (event.style or "").strip(),
                "text": rendered,
            })
        episodes.append({
            "episode_id": row["episode_id"],
            "source_file": path.name,
            "source_sha256": file_hash(path),
            "lines": lines,
        })
    pack = {
        "schema_version": 1,
        "series_id": data["series_id"], "season_id": data["season_id"], "title": data["title"],
        "media_type": data["media_type"], "source_language": data["source_language"], "target_language": data["target_language"],
        "original_audio_language": data["original_audio_language"], "original_audio_status": data["original_audio_status"],
        "original_audio_evidence": data["original_audio_evidence"], "episodes": episodes,
    }
    write_json(output_path, pack, overwrite=True)
    compact = {"status": "ready", "output": str(Path(output_path).resolve()), "sha256": file_hash(output_path),
               "episode_count": len(episodes), "line_count": sum(len(ep["lines"]) for ep in episodes)}
    return compact


def derive_episode_context(context_path, episode_id, output_path):
    context_path = Path(context_path).resolve()
    data = validate_season_context(read_json(context_path))
    episode_id = identifier(episode_id, "episode_id")
    source_map = {row["episode_id"]: row for row in data["episode_sources"]}
    if episode_id not in source_map:
        raise ValueError("Episode is outside season coverage")
    order = {ep: i for i, ep in enumerate(source_map)}
    idx = order[episode_id]

    characters = {cid: row for cid, row in data["characters"].items()
                  if row["visible_from"] is None or order[row["visible_from"]] <= idx}
    relationships = [row for row in data["relationships"] if active(row, episode_id, order)]
    voices = {cid: row for cid, row in data["voices"].items() if cid in characters and active(row, episode_id, order)}
    glossary = {key: row for key, row in data["glossary"].items() if active(row, episode_id, order)}
    recurring = []
    for row in data["recurring_elements"]:
        past = [occ for occ in row["occurrences"] if order[occ["episode_id"]] <= idx]
        if past:
            copy = dict(row); copy["occurrences"] = past; recurring.append(copy)
    notes = data["episode_notes"].get(episode_id, {"translation_summary": "", "notes": [], "songs": []})
    guardrails = [row for row in data["guardrails"] if row["episode_id"] == episode_id]
    uncertainties = [row for row in data["uncertainties"] if row["episode_id"] == episode_id]

    summary = notes["translation_summary"].strip() or f"Season-derived translation context for {episode_id}; use only translation-relevant facts and preserve unresolved ambiguity."
    source = source_map[episode_id]
    result = {
        "context_prepared": True,
        "title": f"{data['title']} {episode_id}",
        "media_type": data["media_type"],
        "summary": summary,
        "glossary": glossary,
        "relationships": relationships,
        "voices": voices,
        "uncertainties": uncertainties,
        "context_sources": [{
            "kind": "subtitle",
            "reference": source["source_file"],
            "finding": f"Season context was derived from the immutable source subtitle for {episode_id} and validated against source hash {source['source_sha256'][:12]}…",
        }],
        "context_checks": {
            "glossary": "populated" if glossary else "reviewed_none_found",
            "relationships": "populated" if relationships else "reviewed_none_found",
            "voices": "populated" if voices else "reviewed_none_found",
            "uncertainties": "populated" if uncertainties else "reviewed_none_found",
            "songs": "populated" if notes["songs"] else "reviewed_none_found",
        },
        "source_language": data["source_language"],
        "target_language": data["target_language"],
        "original_audio_language": data["original_audio_language"],
        "original_audio_status": data["original_audio_status"],
        "original_audio_evidence": data["original_audio_evidence"],
        "songs": notes["songs"],
        "season_context_sha256": file_hash(context_path),
        "characters": characters,
        "recurring_elements": recurring,
        "episode_notes": notes["notes"],
        "translation_guardrails": guardrails,
    }
    write_json(output_path, result, overwrite=True)
    return {"status": "ready", "episode_id": episode_id, "output": str(Path(output_path).resolve()),
            "sha256": file_hash(output_path), "season_context_sha256": file_hash(context_path),
            "counts": {"characters": len(characters), "relationships": len(relationships), "voices": len(voices),
                       "glossary": len(glossary), "recurring_elements": len(recurring), "guardrails": len(guardrails),
                       "uncertainties": len(uncertainties)}}


def derive_filter_review(context_path, episode_id, output_path):
    """Write a compact episode-scoped handoff for the visual content-filter reviewer.

    Text candidates are hints only.  They never authorize a cut without actual
    picture/audio review, and an empty list never means the episode is clean.
    """
    context_path = Path(context_path).resolve()
    data = validate_season_context(read_json(context_path))
    episode_id = identifier(episode_id, "episode_id")
    source_map = {row["episode_id"]: row for row in data["episode_sources"]}
    if episode_id not in source_map:
        raise ValueError("Episode is outside season coverage")
    prefs = read_json(Path(__file__).resolve().parents[1] / "resources" / "preferences.json")
    profile_path = Path(__file__).resolve().parents[1] / "resources" / "content_filter_profile.json"
    profile = read_json(profile_path)
    candidates = [row for row in data["content_filter_candidates"] if row["episode_id"] == episode_id]
    source = source_map[episode_id]
    result = {
        "schema_version": 1,
        "episode_id": episode_id,
        "source_file": source["source_file"],
        "source_sha256": source["source_sha256"],
        "season_context_sha256": file_hash(context_path),
        "auto_content_filter": bool(prefs.get("auto_content_filter")),
        "content_filter_profile": profile,
        "text_candidates": candidates,
        "review_instructions": [
            "Inspect the full episode visually; text candidates are only hints.",
            "Verify every proposed cut against picture/audio and story context.",
            "Do not cut ambiguous material merely because a keyword appears in subtitles.",
            "Write exact reviewed start/end times and concrete evidence before applying any cut.",
        ],
    }
    write_json(output_path, result, overwrite=True)
    return {"status": "ready", "episode_id": episode_id, "output": str(Path(output_path).resolve()),
            "sha256": file_hash(output_path), "candidate_count": len(candidates)}


def inspect_context(path):
    path = Path(path).resolve(); data = validate_season_context(read_json(path))
    result = {"status": "valid", "sha256": file_hash(path), "series_id": data["series_id"], "season_id": data["season_id"],
              "episode_count": len(data["episode_sources"]),
              "counts": {"characters": len(data["characters"]), "relationships": len(data["relationships"]),
                         "voices": len(data["voices"]), "glossary": len(data["glossary"]),
                         "recurring_elements": len(data["recurring_elements"]), "guardrails": len(data["guardrails"]),
                         "uncertainties": len(data["uncertainties"]),
                         "content_filter_candidates": len(data["content_filter_candidates"])}}
    if len(json.dumps(result, ensure_ascii=False)) > 2000:
        raise ValueError("Season context receipt exceeded budget")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare-pack"); p.add_argument("--manifest", required=True); p.add_argument("--output", required=True)
    p = sub.add_parser("validate"); p.add_argument("--context", required=True)
    p = sub.add_parser("inspect"); p.add_argument("--context", required=True)
    p = sub.add_parser("derive-episode"); p.add_argument("--context", required=True); p.add_argument("--episode-id", required=True); p.add_argument("--output", required=True)
    p = sub.add_parser("derive-filter-review"); p.add_argument("--context", required=True); p.add_argument("--episode-id", required=True); p.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare-pack": result = prepare_reading_pack(args.manifest, args.output)
        elif args.command == "derive-episode": result = derive_episode_context(args.context, args.episode_id, args.output)
        elif args.command == "derive-filter-review": result = derive_filter_review(args.context, args.episode_id, args.output)
        elif args.command == "validate":
            validate_season_context(read_json(args.context)); result = {"status": "valid", "sha256": file_hash(args.context)}
        else: result = inspect_context(args.context)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
