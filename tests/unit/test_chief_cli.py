import json

from chief_cli import main
from tests.unit.test_handoff import make_handoff


def test_chief_cli_accepts_a_handoff_file(tmp_path, capsys):
    handoff = make_handoff().model_copy(update={"repository_path": str(tmp_path)})
    handoff_file = tmp_path / "handoff.json"
    handoff_file.write_text(handoff.model_dump_json(), encoding="utf-8")

    assert main(["handoff", "--file", str(handoff_file)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["run_id"] == "run-1"
    assert output["task_ids"] == ["run-1/step-1"]
