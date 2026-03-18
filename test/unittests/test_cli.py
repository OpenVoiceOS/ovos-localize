"""Unit tests for the CLI validation tool."""

from pathlib import Path

from ovos_localize.cli.validate import validate_repo


class TestValidateRepo:
    """Tests for validate_repo()."""

    def test_no_locale_dir(self, tmp_path: Path) -> None:
        """Return 0 when no locale directory exists."""
        assert validate_repo(str(tmp_path)) == 0

    def test_empty_locale(self, tmp_path: Path) -> None:
        """Return 0 when locale dir has no files."""
        (tmp_path / "locale" / "en-US").mkdir(parents=True)
        assert validate_repo(str(tmp_path)) == 0

    def test_valid_files(self, tmp_path: Path) -> None:
        """Return 0 for valid files."""
        en = tmp_path / "locale" / "en-us"
        en.mkdir(parents=True)
        (en / "hello.dialog").write_text("Hello there\nHi!\n")
        (en / "test.voc").write_text("test\n")
        assert validate_repo(str(tmp_path)) == 0

    def test_error_detected(self, tmp_path: Path) -> None:
        """Return 1 when validation errors exist."""
        locale = tmp_path / "locale"
        en = locale / "en-us"
        de = locale / "de-de"
        en.mkdir(parents=True)
        de.mkdir(parents=True)
        # Source has {name} slot, translation missing it
        (en / "greeting.dialog").write_text("Hello {name}\n")
        (de / "greeting.dialog").write_text("Hallo\n")
        assert validate_repo(str(tmp_path)) == 1

    def test_text_format(self, tmp_path: Path, capsys) -> None:
        """Text format prints readable output."""
        en = tmp_path / "locale" / "en-us"
        en.mkdir(parents=True)
        (en / "test.voc").write_text("test\n")
        validate_repo(str(tmp_path), report_format="text")
        captured = capsys.readouterr()
        assert "pass" in captured.out.lower() or captured.out.strip() == ""

    def test_github_format(self, tmp_path: Path, capsys) -> None:
        """GitHub format uses :: annotations."""
        locale = tmp_path / "locale"
        en = locale / "en-us"
        de = locale / "de-de"
        en.mkdir(parents=True)
        de.mkdir(parents=True)
        (en / "greeting.dialog").write_text("Hello {name}\n")
        (de / "greeting.dialog").write_text("Hallo\n")
        validate_repo(str(tmp_path), report_format="github")
        captured = capsys.readouterr()
        assert "::error" in captured.out or "::warning" in captured.out

    def test_json_format(self, tmp_path: Path, capsys) -> None:
        """JSON format outputs valid JSON."""
        import json
        en = tmp_path / "locale" / "en-us"
        en.mkdir(parents=True)
        (en / "test.voc").write_text("test\n")
        validate_repo(str(tmp_path), report_format="json")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
