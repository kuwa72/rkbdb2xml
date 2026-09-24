"""``.env`` ローダの検証。

ローカルでの実機 E2E 用キー (``RB6_DB_KEY``) をリポジトリ外へ
push せずに持たせるため、``.env``（gitignore 済み）から環境変数を
読み込む。既に設定済みの環境変数は上書きしない（CI の secret や
シェル export を優先）。
"""

from pathlib import Path

from tests.conftest import load_dotenv


def test_load_dotenv_sets_variables(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "\n"
        "RB6_DB_KEY=secret-key-1\n"
        "OTHER='quoted value'\n"
        'DOUBLE="double value"\n'
    )
    monkeypatch.delenv("RB6_DB_KEY", raising=False)
    monkeypatch.delenv("OTHER", raising=False)
    monkeypatch.delenv("DOUBLE", raising=False)

    load_dotenv(env_file)

    import os
    assert os.environ["RB6_DB_KEY"] == "secret-key-1"
    assert os.environ["OTHER"] == "quoted value"
    assert os.environ["DOUBLE"] == "double value"


def test_load_dotenv_does_not_override_existing(
    tmp_path: Path, monkeypatch
):
    env_file = tmp_path / ".env"
    env_file.write_text("RB6_DB_KEY=from-file\n")
    monkeypatch.setenv("RB6_DB_KEY", "from-shell")

    load_dotenv(env_file)

    import os
    assert os.environ["RB6_DB_KEY"] == "from-shell"


def test_load_dotenv_missing_file_is_noop(tmp_path: Path):
    load_dotenv(tmp_path / "no-such.env")  # must not raise


def test_repo_env_file_is_gitignored():
    """機密キーを書く ``.env`` が必ず gitignore されていることを保つ。"""
    import subprocess

    repo = Path(__file__).resolve().parent.parent
    out = subprocess.run(
        ["git", "check-ignore", ".env"],
        cwd=repo, capture_output=True, text=True,
    )
    assert out.returncode == 0, (
        ".env が gitignore されていないと DB キーが push の恐れがある"
    )
