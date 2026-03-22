"""Repository scanning and GitHub integration.

Handles:
- Cloning/pulling repos
- Discovering locale directories and skill Python files
- Building the file type inventory
- Generating code context via AST analysis
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ovos_localize.analyzers.ast_analyzer import SkillAnalysis, SkillAnalyzer
from ovos_localize.enums import FileType, IntentSystem
from ovos_localize.lang_utils import normalize_lang_code
from ovos_localize.parsers import get_parser
from ovos_localize.parsers.base import ParsedFile

# Matches BCP-47 language codes: "en", "pt-BR", "zh-hans", etc.
_LANG_DIR_RE = re.compile(r"^[a-z]{2,3}(-[a-zA-Z]{2,})?$")


def _is_lang_dir(name: str) -> bool:
    """Check if a directory name looks like a BCP-47 language code.

    Args:
        name: Directory name to check.

    Returns:
        True if name matches a language code pattern.
    """
    return bool(_LANG_DIR_RE.match(name))


@dataclass
class ScannedFile:
    """A locale file discovered during repo scan.

    Attributes:
        relative_path: Path relative to repo root.
        absolute_path: Full filesystem path.
        file_type: OVOS file type enum.
        lang: BCP-47 language code.
        base_name: Filename without extension.
        intent_system: Detected intent system.
        parsed: Parsed file content.
    """

    relative_path: str
    absolute_path: str
    file_type: FileType
    lang: str
    base_name: str
    intent_system: IntentSystem = IntentSystem.NONE
    parsed: Optional[ParsedFile] = None


@dataclass
class ScanResult:
    """Result of scanning a repository.

    Attributes:
        repo_path: Path to the cloned repository.
        skill_class_name: Discovered skill class name.
        skill_analysis: AST analysis of skill source.
        locale_files: All discovered locale files.
        languages: Set of discovered language codes.
    """

    repo_path: str
    skill_class_name: str = ""
    skill_analysis: Optional[SkillAnalysis] = None
    locale_files: List[ScannedFile] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)


# Map file extensions to FileType enum
_EXT_TO_FILE_TYPE: Dict[str, FileType] = {
    ".intent": FileType.INTENT,
    ".voc": FileType.VOCAB,
    ".dialog": FileType.DIALOG,
    ".entity": FileType.ENTITY,
    ".rx": FileType.REGEX,
    ".value": FileType.VALUE,
}

_EXACT_NAME_TO_FILE_TYPE: Dict[str, FileType] = {
    "skill.json": FileType.SKILL_JSON,
    "settingsmeta.json": FileType.SETTINGS_META,
    "settingsmeta.yml": FileType.SETTINGS_META,
    "settingsmeta.yaml": FileType.SETTINGS_META,
    "noise_words.list": FileType.NOISE_WORDS,
    "word_connectors.json": FileType.WORD_CONNECTORS,
}


def _detect_file_type(filename: str) -> Optional[FileType]:
    """Detect OVOS file type from filename.

    Args:
        filename: The filename (basename).

    Returns:
        FileType or None if not a recognized locale file.
    """
    if filename in _EXACT_NAME_TO_FILE_TYPE:
        return _EXACT_NAME_TO_FILE_TYPE[filename]
    for ext, ft in _EXT_TO_FILE_TYPE.items():
        if filename.endswith(ext):
            return ft
    # Generic .json data files (not skill.json/settingsmeta)
    if filename.endswith(".json"):
        return FileType.RESOURCE_JSON
    return None


def _extract_lang_from_path(file_path: Path, locale_root: Path) -> Optional[str]:
    """Extract language code from a locale file path.

    Expected structure: locale/<lang-code>/...

    Args:
        file_path: Path to the locale file.
        locale_root: Path to the locale/ directory.

    Returns:
        Language code string or None.
    """
    try:
        relative = file_path.relative_to(locale_root)
        parts = relative.parts
        if parts:
            return parts[0]
    except ValueError:
        pass
    return None


def scan_locale_directory(locale_dir: str, repo_root: str = "") -> List[ScannedFile]:
    """Scan a locale directory for all OVOS locale files.

    Args:
        locale_dir: Path to a locale/ directory.
        repo_root: Path to the repository root (for relative paths).

    Returns:
        List of ScannedFile objects.
    """
    locale_path = Path(locale_dir)
    if not locale_path.is_dir():
        return []
    root_path = Path(repo_root) if repo_root else locale_path.parent

    files: List[ScannedFile] = []
    for file_path in sorted(locale_path.rglob("*")):
        if not file_path.is_file():
            continue

        file_type = _detect_file_type(file_path.name)
        if file_type is None:
            continue

        raw_lang = _extract_lang_from_path(file_path, locale_path)
        if not raw_lang:
            continue
        lang = normalize_lang_code(raw_lang)

        base_name = file_path.stem
        parser_cls = get_parser(file_path.name)
        parsed = None
        if parser_cls:
            try:
                parser = parser_cls()
                parsed = parser.parse(str(file_path))
            except Exception:
                pass

        files.append(ScannedFile(
            relative_path=str(file_path.relative_to(root_path)),
            absolute_path=str(file_path),
            file_type=file_type,
            lang=lang,
            base_name=base_name,
            parsed=parsed,
        ))

    return files


class RepoScanner:
    """Scans an OVOS skill repository for locale files and code context.

    Performs:
    1. Git clone/pull
    2. Locale directory discovery
    3. Skill Python source AST analysis
    4. Cross-referencing locale files with code context
    """

    def __init__(self, repos_dir: str = "./repos") -> None:
        """Initialize the scanner.

        Args:
            repos_dir: Base directory for cloned repositories.
        """
        self.repos_dir = Path(repos_dir)
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        self._analyzer = SkillAnalyzer()

    def clone_or_pull(self, org: str, repo: str, branch: str = "dev") -> Path:
        """Clone or update a GitHub repository.

        Args:
            org: GitHub organization.
            repo: Repository name.
            branch: Branch to checkout.

        Returns:
            Path to the local repository.
        """
        repo_dir = self.repos_dir / org / repo
        if repo_dir.exists() and (repo_dir / ".git").exists():
            subprocess.run(
                ["git", "-C", str(repo_dir), "fetch", "origin"],
                capture_output=True, check=False,
            )
            subprocess.run(
                ["git", "-C", str(repo_dir), "checkout", branch],
                capture_output=True, check=False,
            )
            subprocess.run(
                ["git", "-C", str(repo_dir), "pull", "--ff-only"],
                capture_output=True, check=False,
            )
        else:
            repo_dir.parent.mkdir(parents=True, exist_ok=True)
            url = f"https://github.com/{org}/{repo}.git"
            subprocess.run(
                ["git", "clone", "--branch", branch, "--single-branch", url, str(repo_dir)],
                capture_output=True, check=True,
            )
        return repo_dir

    def scan(self, repo_path: str) -> ScanResult:
        """Scan a local repository for locale files and skill code.

        Args:
            repo_path: Path to the repository root.

        Returns:
            ScanResult with all discovered files and analysis.
        """
        path = Path(repo_path)
        result = ScanResult(repo_path=repo_path)

        # Find locale directory
        locale_dir = self._find_locale_dir(path)
        if locale_dir:
            result.locale_files = scan_locale_directory(str(locale_dir), repo_path)

        # Collect languages
        langs = set()
        for f in result.locale_files:
            langs.add(f.lang)
        result.languages = sorted(langs)

        # Analyze skill Python source
        skill_source = self._find_skill_source(path)
        if skill_source:
            analysis = self._analyzer.analyze_file(str(skill_source))
            result.skill_analysis = analysis
            result.skill_class_name = analysis.skill_class_name

            # Cross-reference: set intent_system on locale files
            for scanned in result.locale_files:
                if scanned.file_type == FileType.INTENT:
                    if scanned.base_name + ".intent" in analysis.intent_file_to_handler:
                        scanned.intent_system = IntentSystem.PADATIOUS
                elif scanned.file_type == FileType.VOCAB:
                    if scanned.base_name in analysis.voc_to_intents:
                        scanned.intent_system = IntentSystem.ADAPT

        return result

    def full_sync(self, org: str, repo: str, branch: str = "dev") -> ScanResult:
        """Clone/pull and scan a repository.

        Args:
            org: GitHub organization.
            repo: Repository name.
            branch: Branch to checkout.

        Returns:
            ScanResult from the scan.
        """
        repo_path = self.clone_or_pull(org, repo, branch)
        return self.scan(str(repo_path))

    @staticmethod
    def _find_locale_dir(repo_path: Path) -> Optional[Path]:
        """Find the locale directory in a repository.

        Searches for ``locale/`` or ``res/`` directories containing language
        subdirectories.

        Args:
            repo_path: Path to the repository root.

        Returns:
            Path to locale/ or res/ directory, or None.
        """
        for dir_name in ("locale", "res"):
            candidates = list(repo_path.glob(f"**/{dir_name}"))
            for candidate in candidates:
                if candidate.is_dir():
                    for child in candidate.iterdir():
                        if child.is_dir() and _is_lang_dir(child.name):
                            return candidate
        return None

    @staticmethod
    def _find_skill_source(repo_path: Path) -> Optional[Path]:
        """Find the main skill Python source file.

        Looks for ``__init__.py`` in a package directory that imports from
        ovos_workshop or contains a class with 'Skill' in its name.

        Args:
            repo_path: Path to the repository root.

        Returns:
            Path to the main skill Python file or None.
        """
        # Look for __init__.py files in non-test Python packages
        for init_file in sorted(repo_path.rglob("__init__.py")):
            rel = init_file.relative_to(repo_path)
            if any(part.lower().startswith("test") for part in rel.parts[:-1]):
                continue
            if ".git" in str(init_file):
                continue
            try:
                content = init_file.read_text(encoding="utf-8")
                if "Skill" in content and ("def handle" in content or "intent_handler" in content):
                    return init_file
            except (UnicodeDecodeError, PermissionError):
                continue
        return None
