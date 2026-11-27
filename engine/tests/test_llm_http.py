"""The OpenAI-compatible LLM path and the Jev URL override, against a local stub server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pp import config, jev, llm


@pytest.fixture
def server():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            if self.path.endswith("/chat/completions"):
                out = {"choices": [{"message": {"content": "<think>고민</think>```json\n{\"ok\": 1}\n```"}}]}
            else:
                out = {"model": "local-decision", "usage": {"input_tokens": 7},
                       "answers": {qid: {"type": "noul", "noul": 0.25} for qid in body["questions"]}}
            data = json.dumps(out).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", seen
    httpd.shutdown()


def test_openai_compatible_provider(server, monkeypatch):
    base, seen = server
    monkeypatch.setenv("PP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("PP_LLM_BASE_URL", base + "/v1/")
    monkeypatch.setenv("PP_LLM_MODEL", "k-exaone-test")
    monkeypatch.setenv("PP_LLM_MODEL_REACT", "k-exaone-small")
    monkeypatch.setenv("PP_LLM_API_KEY", "secret")
    assert llm.complete_json("react", "시스템", "질문", model=config.REACT_MODEL) == {"ok": 1}
    assert llm.complete_json("issues", "시스템", "질문", model=config.SYNTH_MODEL) == {"ok": 1}
    assert [s["path"] for s in seen] == ["/v1/chat/completions"] * 2
    assert [s["body"]["model"] for s in seen] == ["k-exaone-small", "k-exaone-test"]
    assert seen[0]["auth"] == "Bearer secret"
    assert seen[0]["body"]["messages"][0] == {"role": "system", "content": "시스템"}
    assert llm.model_label(config.SYNTH_MODEL) == "k-exaone-test"


def test_openai_provider_needs_settings(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "openai")
    monkeypatch.delenv("PP_LLM_BASE_URL", raising=False)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    with pytest.raises(llm.LLMError, match="PP_LLM_BASE_URL"):
        llm.complete_json("react", "s", "p", model=config.REACT_MODEL, retries=0)


def test_jev_url_override_sends_no_typesafe_key(server, monkeypatch):
    base, seen = server
    monkeypatch.setenv("PP_JEV_PROVIDER", "api")
    monkeypatch.setenv("TYPESAFE_API_KEY", "typesafe-secret")
    monkeypatch.setenv("PP_JEV_URL", base + "/v1/systemone")
    assert jev.available()
    out = jev.evaluate("상태", {"q": {"type": "noul", "criteria": "찬성한다"}})
    assert out["answers"]["q"]["noul"] == 0.25
    assert seen[0]["path"] == "/v1/systemone" and seen[0]["auth"] is None
    monkeypatch.setenv("PP_JEV_API_KEY", "local-key")
    jev.evaluate("상태2", {"q": {"type": "noul", "criteria": "찬성한다"}})
    assert seen[1]["auth"] == "Bearer local-key"
