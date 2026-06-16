from __future__ import annotations
import json


def extract_json(text: str) -> dict:
    """从模型输出里抠出第一个完整 JSON 对象：剥代码围栏 + 字符串感知的括号扫描。"""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.startswith("json"):
            s = s[4:]
    start = s.find("{")
    if start == -1:
        raise ValueError("no JSON object found")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start:i + 1])
    raise ValueError("unbalanced JSON object")


import json as _json
import time
import urllib.request
import urllib.error


class LLMError(Exception):
    pass


def _http_transport(url: str, headers: dict, body: str):
    req = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, _json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            payload = _json.loads(e.read().decode("utf-8"))
        except Exception:
            payload = {}
        return e.code, payload


def complete(system: str, user: str, *, base_url: str, api_key: str, model: str,
             transport=_http_transport, max_retries: int = 3, backoff: float = 1.0) -> str:
    """OpenAI 兼容 chat completions。json_mode 默认开；端点 400 则去 response_format 重试一次。
    transport(url, headers, body)->(status, dict) 可注入，便于测试不联网。"""
    api_key = (api_key or "").strip()            # 去掉粘贴时混入的换行/空格
    if not api_key.isascii():
        raise LLMError("API key 含非 ASCII 字符（疑似全角/不可见字符），请重新粘贴纯英文数字 key")
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    base_payload = {"model": model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}]}

    def _once(with_fmt: bool):
        payload = dict(base_payload)
        if with_fmt:
            payload["response_format"] = {"type": "json_object"}
        return transport(url, headers, _json.dumps(payload, ensure_ascii=False))

    with_fmt = True
    last = None
    for attempt in range(max_retries + 1):
        status, data = _once(with_fmt)
        if status == 200:
            return data["choices"][0]["message"]["content"]
        last = (status, data)
        if status == 400 and with_fmt:
            with_fmt = False
            continue
        if status in (429, 500, 502, 503) and attempt < max_retries:
            time.sleep(backoff * (2 ** attempt))
            continue
        break
    raise LLMError(f"LLM request failed: {last}")
