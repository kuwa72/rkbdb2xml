"""CI が RB6_DB_KEY を経由して全シナリオ E2E を再現できることを保つ。"""

from pathlib import Path

WORKFLOW = (
    Path(__file__).parent.parent / ".github" / "workflows" / "test.yml"
)


def test_workflow_passes_rb6_db_key_to_pytest():
    text = WORKFLOW.read_text()

    assert "RB6_DB_KEY: ${{ secrets.RB6_DB_KEY }}" in text, (
        "RB6 暗号化 master.db の E2E はキー未設定だと skip になるため、"
        "CI には secrets.RB6_DB_KEY を環境変数として渡す必要がある"
    )
