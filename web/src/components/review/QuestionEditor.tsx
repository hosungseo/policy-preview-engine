"use client";

import { useEffect, useState } from "react";
import { api, type Finding, type ServiceConfig } from "@/lib/reviewApi";

export interface QuestionValues { question: string; options: string[]; future?: boolean }

export function Findings({ findings }: { findings: Finding[] }) {
  if (!findings.length) return <p className="rv-lint-ok">문항 점검: 눈에 띄는 문제가 없습니다.</p>;
  return (
    <ul className="rv-lint">
      {findings.map((f) => (
        <li key={f.code + f.message} className={`is-${f.level}`}>
          <b>{f.level === "block" ? "실행 불가" : f.level === "warn" ? "고칠 점" : "참고"}</b> {f.message}
          {f.hint && <span className="rv-muted"> {f.hint}</span>}
        </li>
      ))}
    </ul>
  );
}

/** Question + 2–5 options with rule checks shown while typing. */
export default function QuestionEditor({ policyText, values, onChange, config, onFindings }: {
  policyText: string; values: QuestionValues; onChange: (v: QuestionValues) => void; config: ServiceConfig;
  onFindings?: (f: Finding[]) => void;
}) {
  const [findings, setFindings] = useState<Finding[]>([]);
  useEffect(() => {
    if (!values.question.trim()) { setFindings([]); onFindings?.([]); return; }
    const t = setTimeout(async () => {
      try {
        const { findings } = await api<{ findings: Finding[] }>("/api/lint", { method: "POST",
          body: { policy_text: policyText, question: values.question, options: values.options } });
        setFindings(findings);
        onFindings?.(findings);
      } catch { /* checks are advisory while typing */ }
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [policyText, values.question, values.options.join("\u0001")]);

  const setOption = (i: number, v: string) => onChange({ ...values, options: values.options.map((o, j) => (j === i ? v : o)) });
  return (
    <div className="rv-qedit">
      <div className="form-group">
        <div className="form-tit"><label htmlFor="rv-question">문항</label></div>
        <div className="form-conts">
          <textarea id="rv-question" className="krds-input" rows={2} maxLength={config.max_question} value={values.question}
            onChange={(e) => onChange({ ...values, question: e.target.value })} placeholder="예: 만 70세 이상 시내버스 요금 전액 지원에 찬성하십니까?" />
        </div>
      </div>
      <fieldset className="rv-options">
        <legend>선택지 (2~5개)</legend>
        {values.options.map((o, i) => (
          <div key={i} className="rv-option">
            <input className="krds-input" aria-label={`선택지 ${i + 1}`} maxLength={config.max_option} value={o}
              onChange={(e) => setOption(i, e.target.value)} />
            {values.options.length > 2 && (
              <button type="button" className="rv-link" onClick={() => onChange({ ...values, options: values.options.filter((_, j) => j !== i) })}>삭제</button>
            )}
          </div>
        ))}
        {values.options.length < 5 && (
          <button type="button" className="rv-link" onClick={() => onChange({ ...values, options: [...values.options, ""] })}>+ 선택지 추가</button>
        )}
      </fieldset>
      {config.future_available && (
        <label className="rv-future-opt">
          <input type="checkbox" checked={!!values.future} onChange={(e) => onChange({ ...values, future: e.target.checked })} />
          <span><b>5년 뒤 보기</b> — 같은 사람들을 {config.future_year ?? 2030}년의 상태(나이·일·사는 곳·혼인·개인 소득 금액)로 굴려 한 번 더 묻습니다. <span className="rv-muted">응답 수가 약 1.7배가 되고, 결과는 예측이 아니라 가정입니다.</span></span>
        </label>
      )}
      {values.question.trim() && <Findings findings={findings} />}
    </div>
  );
}
