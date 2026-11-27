"""Speech-style guidance so each persona sounds like themselves (harness voice-adapter idea)."""
from __future__ import annotations


def voice_guide(p: dict) -> str:
    age = int(p["age"])
    education = p.get("education_level", "")
    lines = []
    if age >= 70:
        lines.append("말은 짧고 소박하게 하고, 행정 용어 대신 생활 속 말로 풀어서 말한다.")
    elif age >= 55:
        lines.append("살아온 경험에 빗대어 차분하게 말한다. '~지요', '~더라고요' 같은 어미를 자연스럽게 쓴다.")
    elif age >= 35:
        lines.append("집안 형편과 일의 손익을 따져 가며 현실적으로 말한다.")
    else:
        lines.append("구어체로 솔직하게 말한다. '~거든요', '~인데요' 같은 어미를 쓴다.")
    if education in ("무학", "초등학교", "중학교"):
        lines.append("전문 용어나 영어 단어는 쓰지 않는다.")
    elif education == "대학원":
        lines.append("필요하면 근거를 들어 논리적으로 말한다.")
    lines.append(f"자기 일({p.get('occupation', '')})의 현장 표현을 한두 개 섞는다.")
    lines.append("사투리나 지역 고정관념을 과장하지 않고 존댓말로 말한다.")
    return " ".join(lines)
