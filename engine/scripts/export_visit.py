"""Write the 「찾아갈 곳」 view of finished runs to a JSON file the static site can show.
  python scripts/export_visit.py SURVEY_DB OUT.json RUN_ID [RUN_ID ...]
The database is opened read-only.
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ppservice.survey import panel, visit


def main(db_path: str, out: str, *run_ids: str) -> None:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    everyone = panel.load(addons="off")[0]
    items = []
    for run_id in run_ids:
        spec, result, version, finished = db.execute(
            "select spec, result, panel_version, finished_at from runs where id=? and status='succeeded'", (run_id,)).fetchone()
        spec, result = json.loads(spec), json.loads(result)
        answers: dict = {}
        for arm, uuid, probs in db.execute("select arm, uuid, probs from answers where run_id=?", (run_id,)):
            answers.setdefault(arm, {})[uuid] = json.loads(probs)
        people = panel.sample(everyone, spec["n"], spec["seed"])
        view = visit.view(spec, people, answers, result["options"], version, everyone=everyone)
        items.append({"run_id": run_id, "title": spec.get("title", ""), "question": spec["question"], "options": result["options"],
                      "percent": result["percent"], "top": result["top"], "n": view["n"], "date": (finished or "")[:10],
                      "visit": view})
    Path(out).write_text(json.dumps({"items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    print([(i["run_id"], len(i["visit"]["cards"])) for i in items])


if __name__ == "__main__":
    main(*sys.argv[1:])
