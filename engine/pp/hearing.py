"""Virtual hearing: code picks six divergent participants; each speaks in their own voice."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import config, llm, prompts

MODERATOR = {
    1: "지금부터 「{title}」에 관한 가상 공청회를 시작하겠습니다. 오늘 안건은 {agenda}입니다. 먼저 한 분씩 입장을 말씀해 주십시오.",
    2: "말씀 감사합니다. 이제 다른 분의 발언에 동의하거나 반박할 점을 말씀해 주십시오.",
    3: "마지막으로, 정부가 무엇을 바꾸면 받아들일 수 있는지 구체적인 보완안을 하나씩 말씀해 주십시오.",
}


def _demo(person: dict) -> tuple[str, str]:
    return config.age_band(int(person["age"])), config.REGION_OF[person["province"]]


def select_participants(issues: list[dict], reactions: list[dict], people: dict[str, dict], k: int = 6) -> list[str]:
    """One strong voice per top issue, then fill for support balance and demographic spread."""
    by_rid = {r["rid"]: r for r in reactions}
    chosen: list[dict] = []
    for issue in issues[:3]:
        members = sorted((by_rid[m] for m in issue["member_ids"] if m in by_rid),
                         key=lambda r: (-abs(r["support"]), int(r["rid"][1:])))
        used_bands = {_demo(people[c["uuid"]])[0] for c in chosen}
        pick = next((r for r in members if r not in chosen and _demo(people[r["uuid"]])[0] not in used_bands), None)
        pick = pick or next((r for r in members if r not in chosen), None)
        if pick:
            chosen.append(pick)
    while len(chosen) < min(k, len(reactions)):
        bands = {_demo(people[c["uuid"]])[0] for c in chosen}
        regions = {_demo(people[c["uuid"]])[1] for c in chosen}
        favor = sum(c["support"] > 0 for c in chosen)
        reserved = sum(c["support"] <= 0 for c in chosen)  # opposed or neutral

        def score(r: dict) -> float:
            band, region = _demo(people[r["uuid"]])
            s = (band not in bands) + (region not in regions) + 0.5 * abs(r["support"])
            if r["support"] > 0 and favor < 2:
                s += 2
            if r["support"] <= 0 and reserved < 2:
                s += 3  # a seat for the not-in-favour side outranks demographic spread
            return s

        rest = [r for r in reactions if r not in chosen]
        chosen.append(max(rest, key=lambda r: (score(r), -int(r["rid"][1:]))))
    return [c["uuid"] for c in chosen]


def speaker_label(person: dict) -> str:
    return f"{person.get('name') or '참석자'}({person['age']}세·{person['occupation']})"


def render_transcript(turns: list[dict], people: dict[str, dict]) -> str:
    lines = []
    for turn in turns:
        who = "사회자" if turn["speaker"] == "사회자" else speaker_label(people[turn["speaker"]])
        lines.append(f"{who}: {turn['text']}")
    return "\n".join(lines)


def _speech(d: dict) -> dict:
    text = str(d.get("text") or "").strip()
    if not 10 <= len(text) <= 700:
        raise ValueError(f"speech length {len(text)}")
    return {"text": text}


def _summary(d: dict) -> dict:
    out = {}
    for key in ("agreements", "disagreements", "missing"):
        values = d.get(key)
        if not isinstance(values, list):
            raise ValueError(f"missing {key}")
        out[key] = [str(v).strip()[:200] for v in values if str(v).strip()][:3]
    return out


def run_hearing(title: str, policy_text: str, participants: list[str], people: dict[str, dict],
                reactions_by_uuid: dict[str, dict], agenda: list[str], *,
                model: str | None = None, workers: int = 6) -> dict:
    model = model or config.SYNTH_MODEL
    turns: list[dict] = []
    for rnd in (1, 2, 3):
        text = MODERATOR[rnd].format(title=title, agenda=", ".join(f"‘{a}’" for a in agenda))
        turns.append({"round": 0 if rnd == 1 else rnd, "speaker": "사회자", "text": text})
        transcript = render_transcript(turns, people)

        def speak(uuid: str) -> str:
            prompt = prompts.hearing_prompt(people[uuid], policy_text, agenda, reactions_by_uuid[uuid], transcript, rnd)
            return llm.complete_json("hearing", prompts.HEARING_SYSTEM, prompt, model=model, validate=_speech)["text"]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            spoken = list(pool.map(speak, participants))
        turns += [{"round": rnd, "speaker": uuid, "text": said} for uuid, said in zip(participants, spoken)]
    summary = llm.complete_json("hearing_summary", prompts.SUMMARY_SYSTEM,
                                prompts.summary_prompt(title, render_transcript(turns, people)),
                                model=model, validate=_summary)
    return {"participants": participants, "agenda": agenda, "turns": turns, "summary": summary}
