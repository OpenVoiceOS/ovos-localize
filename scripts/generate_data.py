#!/usr/bin/env python3
"""Generate static JSON data files from OVOS skill repositories.

Reads ``skills.txt``, clones each repo (shallow), runs full
scan + analysis + validation, and writes JSON files to ``data/``.

Output files:
- ``data/repos.json`` — index of all skills with coverage summaries
- ``data/coverage.json`` — language × skill coverage matrix
- ``data/validation.json`` — aggregated validation results
- ``data/skills/{skill_id}.json`` — per-skill detail files
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ovos_localize.analyzers.context_builder import ContextCard, build_context_card
from ovos_localize.bracket_expansion import expand_template, clean_text
from ovos_localize.enums import FileType
from ovos_localize.lang_utils import lang_display_name, lang_display_name_native, merge_equivalent_langs
from ovos_localize.parsers.base import ParsedFile
from ovos_localize.sync.github import RepoScanner, ScanResult, ScannedFile
from ovos_localize.validators.rules import ValidationIssue, validate_file

# Repo root (where this script lives under scripts/)
REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_FILE = REPO_ROOT / "skills.txt"
ENABLED_LANGS_FILE = REPO_ROOT / "config" / "enabled_languages.txt"
DATA_DIR = REPO_ROOT / "data"
SKILLS_DATA_DIR = DATA_DIR / "skills"

# GitHub file size limit is 100MB, we aim for 50MB chunks
MAX_FILE_SIZE = 48 * 1024 * 1024  # 48MB


def load_skills_list(path: Path = SKILLS_FILE) -> List[Tuple[str, str]]:
    """Load org/repo pairs from skills.txt.

    Args:
        path: Path to skills.txt file.

    Returns:
        List of (org, repo) tuples.
    """
    skills: List[Tuple[str, str]] = []
    if not path.exists():
        print(f"WARNING: {path} not found", file=sys.stderr)
        return skills
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("/", 1)
        if len(parts) == 2:
            skills.append((parts[0], parts[1]))
    return skills


def _serialize_parsed_file(parsed: Optional[ParsedFile]) -> Optional[Dict[str, Any]]:
    """Serialize a ParsedFile to a JSON-safe dict.

    Args:
        parsed: Parsed file object.

    Returns:
        Dict or None.
    """
    if parsed is None:
        return None
    return {
        "path": parsed.path,
        "file_type": parsed.file_type,
        "lines": [
            {
                "line_number": ln.line_number,
                "text": ln.text,
                "is_comment": ln.is_comment,
                "is_blank": ln.is_blank,
                "slots": ln.slots,
            }
            for ln in parsed.lines
        ],
        "all_slots": parsed.all_slots,
        "line_count": parsed.line_count,
        "errors": parsed.errors,
    }


def _serialize_context_card(card: ContextCard) -> Dict[str, Any]:
    """Serialize a ContextCard to a JSON-safe dict.

    Args:
        card: Context card object.

    Returns:
        Dict representation.
    """
    return asdict(card)


def _serialize_validation_issues(issues: List[ValidationIssue]) -> List[Dict[str, Any]]:
    """Serialize validation issues to JSON-safe dicts.

    Args:
        issues: List of validation issue objects.

    Returns:
        List of dicts.
    """
    return [asdict(issue) for issue in issues]


def _make_skill_id(repo: str) -> str:
    """Derive a skill ID from the repo name.

    Args:
        repo: Repository name (e.g. ``ovos-skill-weather``).

    Returns:
        Skill ID string.
    """
    return repo


def _make_edit_url(org: str, repo: str, relative_path: str, branch: str = "dev") -> str:
    """Build a GitHub edit URL for a locale file.

    Args:
        org: GitHub organization.
        repo: Repository name.
        relative_path: File path relative to repo root.
        branch: Git branch.

    Returns:
        GitHub edit URL string.
    """
    return f"https://github.com/{org}/{repo}/edit/{branch}/{relative_path}"


def _detect_source_lang(skill: Dict[str, Any]) -> str:
    """Detect the source language for a skill (the one with the most files).

    Args:
        skill: Per-skill JSON dict with a ``files`` key.

    Returns:
        BCP-47 language code of the source language.
    """
    lang_counts: Dict[str, int] = {}
    for fd in skill["files"].values():
        for lang in fd["langs"]:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
    if not lang_counts:
        return "en-US"
    # Prefer en-US when tied
    return max(lang_counts, key=lambda k: (lang_counts[k], k == "en-US"))


def _compute_file_coverage(
    files_by_lang: Dict[str, List[ScannedFile]],
    file_type: FileType,
    source_lang: str = "en-US",
) -> Dict[str, float]:
    """Compute per-language coverage for a file type.

    Args:
        files_by_lang: Scanned files grouped by language.
        file_type: The file type to check.
        source_lang: The source language.

    Returns:
        Dict mapping language to coverage percentage (0-100).
    """
    source_files = files_by_lang.get(source_lang, [])
    source_names = {f.base_name for f in source_files if f.file_type == file_type}
    if not source_names:
        return {}

    result: Dict[str, float] = {}
    for lang, files in files_by_lang.items():
        lang_names = {f.base_name for f in files if f.file_type == file_type}
        result[lang] = round(len(lang_names & source_names) / len(source_names) * 100, 1)
    return result


def build_skill_json(
    scan: ScanResult,
    org: str,
    repo: str,
    branch: str = "dev",
) -> Dict[str, Any]:
    """Build per-skill JSON from a scan result.

    Args:
        scan: Scan result from RepoScanner.
        org: GitHub organization.
        repo: Repository name.
        branch: Git branch.

    Returns:
        Dict representing the full skill detail JSON.
    """
    skill_id = _make_skill_id(repo)

    # Group files by base_name across languages
    files_by_base: Dict[str, Dict[str, ScannedFile]] = {}
    for f in scan.locale_files:
        files_by_base.setdefault(f.base_name, {})[f.lang] = f

    # Group by lang for coverage
    files_by_lang: Dict[str, List[ScannedFile]] = {}
    for f in scan.locale_files:
        files_by_lang.setdefault(f.lang, []).append(f)

    # Determine source language (most files, prefer en-US when tied)
    source_lang = max(files_by_lang, key=lambda k: (len(files_by_lang[k]), k == "en-US")) if files_by_lang else "en-US"

    # Build source file lookup for validation
    sources: Dict[str, ParsedFile] = {}
    for f in scan.locale_files:
        if f.lang == source_lang and f.parsed:
            sources[f.base_name] = f.parsed

    # Build file entries
    files_json: Dict[str, Any] = {}
    for base_name, lang_map in sorted(files_by_base.items()):
        # Use any file to determine type/system
        sample = next(iter(lang_map.values()))
        file_key = f"{base_name}.{sample.file_type.value}" if sample.file_type not in (
            FileType.SKILL_JSON, FileType.SETTINGS_META
        ) else sample.file_type.value

        # Build context card from source language file if available
        en_file = lang_map.get(source_lang, sample)
        context_card = build_context_card(
            en_file,
            scan.skill_analysis,
            scan.locale_files,
        )

        langs_json: Dict[str, Any] = {}
        edit_urls: Dict[str, str] = {}
        for lang, scanned in sorted(lang_map.items()):
            # Validate
            issues: List[ValidationIssue] = []
            if scanned.parsed:
                source = sources.get(base_name)
                issues = validate_file(scanned.parsed, source if lang != source_lang else None)

            entries = []
            for ln in (scanned.parsed.content_lines if scanned.parsed else []):
                entry: Dict[str, Any] = {"line": ln.line_number, "text": ln.text}
                # For skill.json / settingsmeta, include key metadata
                if ln.metadata.get("key"):
                    entry["key"] = ln.metadata["key"]
                    entry["translatable"] = ln.metadata.get("translatable", True)
                    if "index" in ln.metadata:
                        entry["index"] = ln.metadata["index"]
                entries.append(entry)

            langs_json[lang] = {
                "entries": entries,
                "line_count": scanned.parsed.line_count if scanned.parsed else 0,
                "slots": scanned.parsed.all_slots if scanned.parsed else [],
                "validation": _serialize_validation_issues(issues),
                "file_path": scanned.relative_path,
            }
            edit_urls[lang] = _make_edit_url(org, repo, scanned.relative_path, branch)

        files_json[file_key] = {
            "type": sample.file_type.value,
            "intent_system": sample.intent_system.value,
            "langs": langs_json,
            "context": _serialize_context_card(context_card),
            "edit_urls": edit_urls,
        }

    return {
        "id": skill_id,
        "repo": f"{org}/{repo}",
        "skill_class": scan.skill_class_name,
        "source_file": scan.skill_analysis.source_file if scan.skill_analysis else "",
        "languages": scan.languages,
        "files": files_json,
    }


def _load_enabled_languages() -> List[str]:
    """Return language codes from ``config/enabled_languages.txt``.

    Lines starting with ``#`` and blank lines are ignored.  The codes are
    normalised via :func:`~ovos_localize.lang_utils.normalize_lang_code` so
    they are consistent with the rest of the pipeline.

    Returns:
        Sorted list of normalised BCP-47 codes.
    """
    from ovos_localize.lang_utils import normalize_lang_code

    if not ENABLED_LANGS_FILE.exists():
        return []
    codes: List[str] = []
    for raw in ENABLED_LANGS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            codes.append(normalize_lang_code(line))
        except Exception:
            pass  # skip malformed lines silently
    return sorted(set(codes))


def build_coverage_json(all_skills: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build coverage matrix JSON from all skill data.

    Args:
        all_skills: List of per-skill JSON dicts.

    Returns:
        Coverage matrix dict.
    """
    all_langs: set = set(_load_enabled_languages())
    skill_ids: List[str] = []
    matrix: Dict[str, Dict[str, Dict[str, float]]] = {}

    for skill in all_skills:
        sid = skill["id"]
        skill_ids.append(sid)
        all_langs.update(skill["languages"])

        source_lang = _detect_source_lang(skill)

        # Count files by type per language
        type_counts: Dict[str, Dict[str, int]] = {}
        source_counts: Dict[str, int] = {}
        for file_key, file_data in skill["files"].items():
            ft = file_data["type"]
            for lang, lang_data in file_data["langs"].items():
                type_counts.setdefault(ft, {}).setdefault(lang, 0)
                type_counts[ft][lang] += 1
                if lang == source_lang:
                    source_counts[ft] = source_counts.get(ft, 0) + 1

        # Compute per-language coverage
        lang_coverage: Dict[str, Dict[str, float]] = {}
        for lang in skill["languages"]:
            cov: Dict[str, float] = {}
            total_source = 0
            total_translated = 0
            for ft, sc in source_counts.items():
                translated = type_counts.get(ft, {}).get(lang, 0)
                pct = round(translated / sc * 100, 1) if sc else 0.0
                cov[f"{ft}_pct"] = pct
                total_source += sc
                total_translated += translated
            cov["combined_pct"] = round(total_translated / total_source * 100, 1) if total_source else 0.0
            lang_coverage[lang] = cov

        matrix[sid] = lang_coverage

    # Merge equivalent language codes (e.g. "ca" + "ca-ES" → "ca-ES")
    merge_map = merge_equivalent_langs(list(all_langs))
    merged_langs = sorted(set(merge_map.values()))

    # Merge matrix entries
    for sid in skill_ids:
        old = matrix.get(sid, {})
        merged: Dict[str, Dict[str, float]] = {}
        for raw_lang, cov in old.items():
            canonical = merge_map.get(raw_lang, raw_lang)
            if canonical not in merged:
                merged[canonical] = cov
            else:
                # Keep the one with higher combined_pct
                if cov.get("combined_pct", 0) > merged[canonical].get("combined_pct", 0):
                    merged[canonical] = cov
        matrix[sid] = merged

    lang_meta: Dict[str, Dict[str, str]] = {}
    for code in merged_langs:
        lang_meta[code] = {
            "display": lang_display_name(code),
            "native": lang_display_name_native(code),
        }

    return {
        "skills": skill_ids,
        "languages": merged_langs,
        "lang_meta": lang_meta,
        "merge_map": merge_map,
        "matrix": matrix,
    }


def build_repos_json(all_skills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build repos index JSON.

    Args:
        all_skills: List of per-skill JSON dicts.

    Returns:
        List of repo summary dicts.
    """
    repos: List[Dict[str, Any]] = []
    for skill in all_skills:
        file_count = sum(
            len(fd["langs"])
            for fd in skill["files"].values()
        )
        repos.append({
            "id": skill["id"],
            "repo": skill["repo"],
            "skill_class": skill["skill_class"],
            "languages": skill["languages"],
            "file_count": file_count,
        })
    return repos


def build_validation_json(all_skills: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build aggregated validation JSON.

    Args:
        all_skills: List of per-skill JSON dicts.

    Returns:
        Validation summary dict.
    """
    total_errors = 0
    total_warnings = 0
    by_rule: Dict[str, int] = {}
    by_skill: List[Dict[str, Any]] = []

    for skill in all_skills:
        skill_errors = 0
        skill_warnings = 0
        for file_data in skill["files"].values():
            for lang_data in file_data["langs"].values():
                for issue in lang_data["validation"]:
                    rule = issue["rule_name"]
                    by_rule[rule] = by_rule.get(rule, 0) + 1
                    if issue["severity"] == "error":
                        total_errors += 1
                        skill_errors += 1
                    elif issue["severity"] == "warning":
                        total_warnings += 1
                        skill_warnings += 1

        by_skill.append({
            "id": skill["id"],
            "errors": skill_errors,
            "warnings": skill_warnings,
        })

    return {
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "by_rule": by_rule,
        "by_skill": by_skill,
    }


def build_stats_json(all_skills: List[Dict[str, Any]], coverage: Dict[str, Any]) -> Dict[str, Any]:
    """Build aggregate language statistics (replaces lang-support-tracker metrics).

    Computes per-language, per-filetype coverage across all skills.

    Args:
        all_skills: List of per-skill JSON dicts.
        coverage: Coverage matrix from build_coverage_json.

    Returns:
        Stats dict with per-language breakdown.
    """
    file_types = ["intent", "voc", "dialog", "entity", "rx", "value", "skill.json", "resource_json"]
    langs = list(coverage.get("languages", []))

    # Count source files per type (source lang varies per skill)
    source_counts: Dict[str, int] = {}
    for skill in all_skills:
        sl = _detect_source_lang(skill)
        for fd in skill["files"].values():
            ft = fd["type"]
            if sl in fd["langs"]:
                source_counts[ft] = source_counts.get(ft, 0) + 1

    total_source = sum(source_counts.values())

    # Per-language stats
    lang_stats: Dict[str, Any] = {}
    for lang in langs:
        type_counts: Dict[str, int] = {}
        skills_with_any = 0
        skills_fully_translated = 0

        for skill in all_skills:
            sl = _detect_source_lang(skill)
            has_any = False
            # A skill is fully translated when every source file has a translation
            source_total = 0
            source_have = 0
            for fd in skill["files"].values():
                ft = fd["type"]
                has_source = sl in fd["langs"]
                has_lang = lang in fd["langs"]
                if has_lang:
                    has_any = True
                # Only count translations of files that exist in source
                if has_source and has_lang:
                    type_counts[ft] = type_counts.get(ft, 0) + 1
                if has_source:
                    source_total += 1
                    if has_lang:
                        source_have += 1
            if has_any:
                skills_with_any += 1
            if source_total > 0 and source_have == source_total:
                skills_fully_translated += 1

        total_translated = sum(type_counts.values())
        combined_pct = round(total_translated / total_source * 100, 1) if total_source else 0

        per_type: Dict[str, Dict[str, Any]] = {}
        for ft in file_types:
            src = source_counts.get(ft, 0)
            have = type_counts.get(ft, 0)
            per_type[ft] = {
                "source": src,
                "translated": have,
                "pct": round(have / src * 100, 1) if src else 0,
            }

        lang_stats[lang] = {
            "total_files": total_translated,
            "total_source": total_source,
            "combined_pct": combined_pct,
            "skills_any_coverage": skills_with_any,
            "skills_fully_translated": skills_fully_translated,
            "by_type": per_type,
        }

    return {
        "generated": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "total_skills": len(all_skills),
        "total_source_files": total_source,
        "source_by_type": source_counts,
        "languages": lang_stats,
    }


def export_intent_dataset(all_skills: List[Dict[str, Any]], output_path: Path) -> int:
    """Export a unified intent dataset TSV, split into chunks if necessary.

    Each row: lang, skill_id, file_key, utterance.
    Expands templates, lowercases, and deduplicates phrases.

    Args:
        all_skills: List of per-skill JSON dicts.
        output_path: Path to write the TSV file.

    Returns:
        Number of rows written.
    """
    chunk_index = 0
    rows = 0
    current_f = None
    current_size = 0

    def get_path(idx):
        if idx == 0:
            return output_path
        return output_path.with_name(f"{output_path.stem}_{idx}{output_path.suffix}")

    try:
        current_f = get_path(chunk_index).open("w", encoding="utf-8")
        current_f.write("lang\tskill\tfile\tutterance\n")
        current_size = current_f.tell()

        for skill in all_skills:
            for file_key, fd in skill["files"].items():
                if fd["type"] not in ("intent", "dialog", "voc"):
                    continue
                for lang, ld in fd["langs"].items():
                    seen = set()
                    for entry in ld.get("entries", []):
                        template = entry.get("text", "").strip()
                        if not template or template.startswith("#"):
                            continue

                        # Expand templates and clean
                        for expanded in expand_template(template):
                            cleaned = clean_text(expanded)
                            if not cleaned or cleaned in seen:
                                continue
                            seen.add(cleaned)

                            line = f"{lang}\t{skill['id']}\t{file_key}\t{cleaned}\n"
                            line_bytes = len(line.encode("utf-8"))

                            # Split if file exceeds MAX_FILE_SIZE
                            if current_size + line_bytes > MAX_FILE_SIZE:
                                current_f.close()
                                chunk_index += 1
                                current_f = get_path(chunk_index).open("w", encoding="utf-8")
                                current_f.write("lang\tskill\tfile\tutterance\n")
                                current_size = current_f.tell()

                            current_f.write(line)
                            current_size += line_bytes
                            rows += 1
    finally:
        if current_f:
            current_f.close()

    return rows


def build_entities_json(all_skills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build entity index from .entity files and {slots} in .intent files.

    For each {slot} used in .intent files, checks if a corresponding
    .entity file exists. This surfaces gaps in NER training data.

    Args:
        all_skills: List of per-skill JSON dicts.

    Returns:
        List of entity dicts.
    """
    entities: List[Dict[str, Any]] = []

    for skill in all_skills:
        # Collect all entity file base names
        entity_files = set()
        for fk, fd in skill["files"].items():
            if fd["type"] == "entity":
                entity_files.add(fd.get("_base_name", fk.replace(".entity", "")))

        # Collect slots from intent files
        intent_slots: Dict[str, List[str]] = {}  # slot_name → list of intent files using it
        for fk, fd in skill["files"].items():
            if fd["type"] != "intent":
                continue
            en_data = fd["langs"].get(_detect_source_lang(skill), {})
            for entry in en_data.get("entries", []):
                import re
                for slot in re.findall(r"\{(\w+)\}", entry.get("text", "")):
                    intent_slots.setdefault(slot, []).append(fk)

        # Build entity entries from .entity files
        for fk, fd in skill["files"].items():
            if fd["type"] != "entity":
                continue
            lang_data = {}
            for lang, ld in fd["langs"].items():
                lang_data[lang] = {
                    "count": len(ld.get("entries", [])),
                    "samples": [e["text"] for e in ld.get("entries", [])[:15]],
                }
            base = fk.replace(".entity", "")
            entities.append({
                "name": base,
                "file_key": fk,
                "type": "entity",
                "skill": skill["id"],
                "repo": skill["repo"],
                "has_entity_file": True,
                "used_in_intents": sorted(set(intent_slots.get(base, []))),
                "langs": lang_data,
            })

        # Add slots from intents that DON'T have .entity files
        for slot, intents in intent_slots.items():
            if slot in entity_files:
                continue  # Already covered by .entity file above
            entities.append({
                "name": slot,
                "file_key": None,
                "type": "slot",
                "skill": skill["id"],
                "repo": skill["repo"],
                "has_entity_file": False,
                "used_in_intents": list(set(intents)),
                "langs": {},
            })

    # Sort: slots without entity files first (gaps), then by name
    entities.sort(key=lambda e: (e["has_entity_file"], e["name"], e["skill"]))
    return entities


def main() -> None:
    """Run data generation pipeline."""
    skills_list = load_skills_list()
    if not skills_list:
        print("No skills found in skills.txt", file=sys.stderr)
        sys.exit(1)

    print(f"Processing {len(skills_list)} skills...")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SKILLS_DATA_DIR.mkdir(parents=True, exist_ok=True)

    scanner = RepoScanner(str(REPO_ROOT / "repos"))
    all_skills: List[Dict[str, Any]] = []

    for i, (org, repo) in enumerate(skills_list, 1):
        print(f"  [{i}/{len(skills_list)}] {org}/{repo}...", end=" ", flush=True)
        try:
            scan = scanner.full_sync(org, repo)
            if not scan.locale_files:
                print("SKIPPED (no locale files)")
                continue
            skill_json = build_skill_json(scan, org, repo)
            all_skills.append(skill_json)

            # Write per-skill JSON (split if too large)
            skill_id = skill_json['id']
            skill_path = SKILLS_DATA_DIR / f"{skill_id}.json"
            
            # Remove indent to save space
            content = json.dumps(skill_json, ensure_ascii=False)
            content_bytes = content.encode("utf-8")
            if len(content_bytes) > MAX_FILE_SIZE:
                # Split 'files' key if too large
                all_files = list(skill_json["files"].items())
                chunk_index = 0
                
                # Copy metadata
                main_json = {k: v for k, v in skill_json.items() if k != "files"}
                main_json["files"] = {}
                main_json["chunks"] = []
                
                current_chunk_json = {"files": {}}
                current_chunk_size = 15 # approximate size of '{"files":{}}'
                
                for fk, fv in all_files:
                    # Quick size estimation for this entry
                    file_content = json.dumps({fk: fv}, ensure_ascii=False)
                    file_size = len(file_content.encode("utf-8"))
                    
                    if current_chunk_size + file_size > MAX_FILE_SIZE and current_chunk_json["files"]:
                        # Save current chunk
                        chunk_name = f"{skill_id}_{chunk_index}.json"
                        (SKILLS_DATA_DIR / chunk_name).write_text(
                            json.dumps(current_chunk_json, ensure_ascii=False)
                        )
                        main_json["chunks"].append(chunk_name)
                        chunk_index += 1
                        current_chunk_json = {"files": {}}
                        current_chunk_size = 15
                    
                    current_chunk_json["files"][fk] = fv
                    current_chunk_size += file_size
                
                # Save last chunk
                if current_chunk_json["files"]:
                    chunk_name = f"{skill_id}_{chunk_index}.json"
                    (SKILLS_DATA_DIR / chunk_name).write_text(
                        json.dumps(current_chunk_json, ensure_ascii=False)
                    )
                    main_json["chunks"].append(chunk_name)
                
                skill_path.write_text(json.dumps(main_json, ensure_ascii=False))
                print(f"{len(scan.languages)} langs, {len(scan.locale_files)} files (SPLIT into {len(main_json['chunks'])} chunks)")
            else:
                skill_path.write_text(content)
                print(f"{len(scan.languages)} langs, {len(scan.locale_files)} files")
            if scan.bad_lang_codes:
                print(f"    WARNING: bare lang codes (missing region) in {org}/{repo}: {', '.join(sorted(scan.bad_lang_codes))}", file=sys.stderr)
        except Exception as e:
            print(f"FAILED: {e}", file=sys.stderr)
            continue

    # Write aggregate files
    repos_path = DATA_DIR / "repos.json"
    repos_path.write_text(json.dumps(build_repos_json(all_skills), ensure_ascii=False))

    coverage_data = build_coverage_json(all_skills)
    coverage_path = DATA_DIR / "coverage.json"
    coverage_path.write_text(json.dumps(coverage_data, ensure_ascii=False))

    validation_path = DATA_DIR / "validation.json"
    validation_path.write_text(json.dumps(build_validation_json(all_skills), ensure_ascii=False))

    stats_data = build_stats_json(all_skills, coverage_data)
    stats_path = DATA_DIR / "stats.json"
    stats_path.write_text(json.dumps(stats_data, ensure_ascii=False))

    dataset_path = DATA_DIR / "dataset.tsv"
    dataset_rows = export_intent_dataset(all_skills, dataset_path)

    entities_data = build_entities_json(all_skills)
    entities_path = DATA_DIR / "entities.json"
    entities_path.write_text(json.dumps(entities_data, ensure_ascii=False))
    gaps = sum(1 for e in entities_data if not e["has_entity_file"])

    print(f"\nDone. {len(all_skills)} skills → data/")
    print(f"  repos.json: {len(all_skills)} entries")
    print(f"  coverage.json: {len(coverage_data['languages'])} languages")
    print(f"  stats.json: {len(stats_data['languages'])} languages")
    print(f"  dataset.tsv: {dataset_rows} rows")
    print(f"  entities.json: {len(entities_data)} entities ({gaps} missing .entity files)")


if __name__ == "__main__":
    main()
