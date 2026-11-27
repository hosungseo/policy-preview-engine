"""persona.db -> population.json (national reference distribution for the panel page).

Run: ../.venv/bin/python scripts/build_population.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pp import config, personas  # noqa: E402


def main() -> None:
    pop = personas.population(personas.connect())
    unknown = set(pop["province"]) - set(config.PROVINCE_DISPLAY)
    if unknown:
        raise SystemExit(f"unmapped province values: {sorted(unknown)}")
    config.population_json().write_text(json.dumps(pop, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {config.population_json()} total={pop['total']:,}")


if __name__ == "__main__":
    main()
