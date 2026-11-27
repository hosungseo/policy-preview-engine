"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

interface Example { id: string; title: string; kind: string; agency: string; text: string }

const KINDS = ["입법예고", "행정예고", "정책안", "가상 정책안", "정책 요약"];

export default function NewForm({ examples }: { examples: Example[] }) {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("입법예고");
  const [agency, setAgency] = useState("");
  const [text, setText] = useState("");
  const [loaded, setLoaded] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function load(example: Example) {
    setTitle(example.title);
    setKind(KINDS.includes(example.kind) ? example.kind : "정책안");
    setAgency(example.agency);
    setText(example.text);
    setLoaded(example.id);
    setNotice(null);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const example = examples.find((x) => x.id === loaded);
    if (example && example.text === text && example.title === title) {
      router.push(`/runs/${example.id}/progress/`);
      return;
    }
    setNotice("시제품에서는 위 예시 정책만 실행할 수 있습니다. 새 정책은 로컬 엔진에서 실행합니다: python -m pp run policies/새정책.json");
  }

  return (
    <form className="pp-card pp-new-form" onSubmit={submit}>
      <div className="pp-warn" role="note">
        <strong>비공개 초안 입력 주의</strong>
        <p>
          입력한 정책 문서는 외부 AI(Anthropic Claude)로 전송됩니다. 비공개 초안을 넣기 전에 기관 보안 지침을 확인하세요. 입력에
          따른 책임은 입력자에게 있습니다.
        </p>
      </div>
      <p className="pp-poc">시제품(POC): 이 화면에서는 아래 예시 정책만 실행 결과로 연결됩니다.</p>
      <div className="pp-examples">
        <span>예시 불러오기</span>
        {examples.map((example) => (
          <button key={example.id} type="button" onClick={() => load(example)}
            className={`krds-btn small ${loaded === example.id ? "primary" : "secondary"}`}>
            {example.title}
          </button>
        ))}
      </div>
      <div className="form-group">
        <div className="form-tit"><label htmlFor="pp-title">정책 이름</label></div>
        <div className="form-conts">
          <input id="pp-title" className="krds-input" value={title} onChange={(e) => setTitle(e.target.value)}
            placeholder="예: 생명안전기본법 시행령 제정안" />
        </div>
      </div>
      <div className="pp-new-row">
        <div className="form-group">
          <div className="form-tit"><label htmlFor="pp-kind">유형</label></div>
          <div className="form-conts">
            <select id="pp-kind" className="krds-form-select" value={kind} onChange={(e) => setKind(e.target.value)}>
              {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </div>
        </div>
        <div className="form-group">
          <div className="form-tit"><label htmlFor="pp-agency">소관</label></div>
          <div className="form-conts">
            <input id="pp-agency" className="krds-input" value={agency} onChange={(e) => setAgency(e.target.value)} placeholder="예: 행정안전부" />
          </div>
        </div>
      </div>
      <div className="form-group">
        <div className="form-tit"><label htmlFor="pp-text">정책 본문</label></div>
        <div className="form-conts">
          <div className="textarea-wrap">
            <textarea id="pp-text" className="krds-input pp-textarea" value={text} onChange={(e) => setText(e.target.value)}
              placeholder="입법예고문의 제정·개정 이유와 주요내용, 또는 정책안 본문을 붙여 넣으세요." />
          </div>
        </div>
        <p className="form-hint">‘1.’, ‘가.’ 같은 항목 번호가 있으면 항목별로 반응을 모아 보여줍니다.</p>
      </div>
      <div className="pp-card-soft pp-panel-info">
        <b>패널 구성</b>
        <ul>
          <li>대표 패널 300명 — 합성 인물 100만 명에서 시도·연령대·성별 비율대로 층화 추출</li>
          <li>영향권 패널 최대 100명 — 정책문에서 영향받을 사람을 속성 조건·키워드·의미 검색으로 자동 탐색</li>
        </ul>
      </div>
      {notice && <p className="pp-new-notice" role="status">{notice}</p>}
      <div className="pp-actions">
        <button type="submit" className="krds-btn large primary">의견수렴 설계 시작</button>
      </div>
    </form>
  );
}
