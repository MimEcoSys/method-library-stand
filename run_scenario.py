"""Manual stand: Tester <-> tested Claude Code (with Open MCP) <-> Evaluator.

Usage: python3 run_scenario.py <scenario_id|all> [--repeats N] [--tag TAG]
Writes runs/<YYYY-MM-DD>/<scenario_id>-<TAG>-r<i>.json per run (transcript, tool calls,
verdict, versions) and runs/<YYYY-MM-DD>/summary-<TAG>.json with pass share and the three
counters per scenario. A run that fails is retried once; if it fails again it is reported
as a failure and left out of the share.

Every claude process runs in a fresh empty temporary directory outside this
repository, so no project CLAUDE.md or settings reach the Tester, the tested
object or the Evaluator.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKDIR = Path(tempfile.mkdtemp(prefix="method-library-stand-"))
shutil.copy(HERE / "mcp.json", WORKDIR / "mcp.json")
MAX_TESTER_TURNS = 15
END_MARK = "ТЕСТ ЗАКОНЧЕН"
BASE = ["claude", "-p", "--setting-sources", "project", "--strict-mcp-config"]

# One OpenRouter key pays for all three parties; it is read from the environment only.
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
if not OPENROUTER_KEY:
    sys.exit("OPENROUTER_API_KEY is not set (see README, 'Key')")
JUDGE_MODEL = os.environ.get("STAND_JUDGE_MODEL", "openai/gpt-6.2-sol")      # Tester and Evaluator
OBJECT_MODEL = os.environ.get("STAND_OBJECT_MODEL", "anthropic/claude-sonnet-4.6")  # tested Claude Code
OBJECT_ENV = {
    **os.environ,
    "ANTHROPIC_BASE_URL": "https://openrouter.ai/api",
    "ANTHROPIC_AUTH_TOKEN": OPENROUTER_KEY,
    "ANTHROPIC_API_KEY": "",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": OBJECT_MODEL,
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": OBJECT_MODEL,
    "ANTHROPIC_DEFAULT_OPUS_MODEL": OBJECT_MODEL,
}


def run_claude(args, prompt, timeout=600):
    proc = subprocess.run(BASE + args + [prompt], cwd=WORKDIR, capture_output=True,
                          text=True, timeout=timeout, env=OBJECT_ENV)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[-500:]}")
    return proc.stdout


def ask_agent(system_prompt, history, user_text):
    """Text-only agent (Tester or Evaluator) through the OpenRouter chat API.

    `history` is the list of earlier user/assistant messages and is extended in place.
    """
    history.append({"role": "user", "content": user_text})
    body = json.dumps({"model": JUDGE_MODEL,
                       "messages": [{"role": "system", "content": system_prompt}] + history}).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        text = json.loads(resp.read())["choices"][0]["message"]["content"].strip()
    history.append({"role": "assistant", "content": text})
    return text


def _result_ids(content):
    """Pull release_id and card sha256 out of a tool result (text blocks holding JSON)."""
    text = content if isinstance(content, str) else "".join(
        b.get("text", "") for b in content if isinstance(b, dict))
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    ids = {}
    if isinstance(data, dict):
        if data.get("release_id"):
            ids["release_id"] = data["release_id"]
        if data.get("sha256"):
            ids["card_sha256"] = data["sha256"]
    return ids


def ask_object(message, session_id):
    """Tested object: Claude Code with the library MCP. Returns (text, calls, sid, models)."""
    args = ["--model", "sonnet", "--mcp-config", "mcp.json", "--tools", "",
            "--allowedTools", "mcp__lib__search mcp__lib__read",
            "--output-format", "stream-json", "--verbose"]
    if session_id:
        args += ["--resume", session_id]
    calls, text, sid, models = [], "", session_id, []
    pending = {}
    for line in run_claude(args, message).splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        kind = ev.get("type")
        if kind == "assistant":
            for part in ev["message"].get("content", []):
                if part.get("type") == "tool_use":
                    call = {"tool": part["name"], "input": part.get("input")}
                    pending[part["id"]] = call
                    calls.append(call)
        elif kind == "user":
            for part in ev.get("message", {}).get("content", []):
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    call = pending.get(part.get("tool_use_id"))
                    if call is not None:
                        content = part.get("content")
                        call["result_excerpt"] = json.dumps(content, ensure_ascii=False)[:400]
                        call["is_error"] = bool(part.get("is_error"))
                        call.update(_result_ids(content))
        elif kind == "result":
            text = ev.get("result", "").strip()
            sid = ev.get("session_id", sid)
            models = list((ev.get("modelUsage") or {}).keys())
    return text, calls, sid, models


def render_transcript(turns):
    lines = []
    for t in turns:
        lines.append(f"ПОЛЬЗОВАТЕЛЬ: {t['user']}")
        for c in t["calls"]:
            lines.append(f"[обращение к библиотеке: {c['tool']} {json.dumps(c['input'], ensure_ascii=False)}"
                         f" -> {c.get('result_excerpt', '')[:200]}]")
        lines.append(f"АССИСТЕНТ: {t['assistant']}")
    return "\n".join(lines)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def server_fingerprint():
    """What the server announces on connect: version, instruction text hash, tool descriptions hash."""
    url = json.loads((HERE / "mcp.json").read_text())["mcpServers"]["lib"]["url"]

    def rpc(method, params, rid):
        body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "User-Agent": "method-library-stand/1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
        data_lines = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
        return json.loads(data_lines[-1] if data_lines else raw)["result"]

    try:
        init = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                  "clientInfo": {"name": "method-library-stand", "version": "1"}}, 1)
        tools = rpc("tools/list", {}, 2)["tools"]
        instructions = init.get("instructions", "")
        return {"server_info": init.get("serverInfo"), "instructions_len": len(instructions),
                "instructions_sha256": sha(instructions),
                "tool_descriptions_sha256": sha(json.dumps({x["name"]: x.get("description", "") for x in tools},
                                                           sort_keys=True))}
    except Exception as exc:  # recorded in every run so a missing fingerprint is visible, not silent
        print(f"server fingerprint failed: {exc!r}", file=sys.stderr)
        return {"error": repr(exc)}


def stand_version():
    proc = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True)
    return proc.stdout.strip() or "unknown"


def counters(turns, scenario, verdict):
    """The three counters of concept part 6. None means 'not applicable to this scenario'."""
    calls = [c for tn in turns for c in tn["calls"]]
    searched = any(c["tool"].endswith("search") for c in calls)
    read = any(c["tool"].endswith("read") for c in calls)
    expected = scenario.get("library_expected")
    passed = isinstance(verdict, dict) and verdict.get("result") == "пройден"
    return {
        "called_when_needed": (int(searched) if expected == "yes" else None),
        "guided_by_method": (int(passed) if expected == "yes" and read else None),
        "wrong_calls": (len(calls) if expected == "no" else None),
    }


def run_once(scenario, tag, fingerprint):
    tester_prompt = (HERE / "prompts" / "tester.md").read_text()
    evaluator_prompt = (HERE / "prompts" / "evaluator.md").read_text()
    t = scenario["tester"]
    opening = (f"Сценарий.\nПервая реплика: {t['first']}\nФакты: {t['facts']}\n"
               f"Готовый ответ на предложение метода: {t['ready_answer']}")
    tester_history = []
    tester_msg = ask_agent(tester_prompt, tester_history, opening)

    turns, object_sid, end_line, models = [], None, None, []
    for _ in range(MAX_TESTER_TURNS):
        if END_MARK in tester_msg:
            end_line = tester_msg[tester_msg.index(END_MARK):].splitlines()[0]
            break
        reply, calls, object_sid, models = ask_object(tester_msg, object_sid)
        turns.append({"user": tester_msg, "assistant": reply, "calls": calls})
        tester_msg = ask_agent(tester_prompt, tester_history, reply or "(пустой ответ)")
    else:
        end_line = f"{END_MARK} | причина=лимит | не_хватило_фактов=?"

    transcript = render_transcript(turns)
    criteria = "\n".join(f"{k}: {v}" for k, v in scenario["criteria"].items())
    eval_input = (f"Ожидание: {scenario['expectation']}\nКритерии:\n{criteria}\n\n"
                  f"Итог Тестировщика: {end_line}\n\nЗапись беседы:\n{transcript}")
    verdict_raw = ask_agent(evaluator_prompt, [], eval_input)
    try:
        verdict = json.loads(verdict_raw.strip().removeprefix("```json").removesuffix("```").strip())
    except json.JSONDecodeError:
        verdict = {"unparsed": verdict_raw}

    calls_all = [c for tn in turns for c in tn["calls"]]
    return {
        "scenario": scenario["id"], "run": tag, "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "versions": {
            "stand_commit": stand_version(),
            "server": fingerprint,
            "release_id": next((c["release_id"] for c in calls_all if "release_id" in c), None),
            "card_sha256": {c["input"].get("method_id"): c["card_sha256"] for c in calls_all if "card_sha256" in c},
            "tester_prompt_sha256": sha(tester_prompt), "evaluator_prompt_sha256": sha(evaluator_prompt),
            "scenario_sha256": sha(json.dumps(scenario, ensure_ascii=False, sort_keys=True)),
            "judge_model": JUDGE_MODEL, "object_model_requested": OBJECT_MODEL, "object_models": models,
        },
        "tester_end": end_line, "turns": turns, "verdict": verdict,
        "counters": counters(turns, scenario, verdict),
    }


def summarize(results):
    """Pass share and counter totals per scenario; failed runs are listed, not counted."""
    summary = {}
    for sid, runs in results.items():
        ok = [r for r in runs if "error" not in r]
        passed = [r for r in ok if isinstance(r["verdict"], dict) and r["verdict"].get("result") == "пройден"]
        entry = {"runs": len(runs), "failed_runs": len(runs) - len(ok), "passed": len(passed),
                 "pass_share": round(len(passed) / len(ok), 2) if ok else None}
        for key in ("called_when_needed", "guided_by_method", "wrong_calls"):
            vals = [r["counters"][key] for r in ok if r["counters"][key] is not None]
            entry[key] = ({"sum": sum(vals), "of": len(vals)} if vals else None)
        summary[sid] = entry
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scenario", help="scenario id or 'all'")
    ap.add_argument("--repeats", type=int, default=1, help="runs per scenario")
    ap.add_argument("--tag", default=time.strftime("%H%M%S"))
    args = ap.parse_args()

    scenarios = json.loads((HERE / "scenarios.json").read_text())
    chosen = scenarios if args.scenario == "all" else [s for s in scenarios if s["id"] == args.scenario]
    if not chosen:
        sys.exit(f"unknown scenario: {args.scenario}")
    out_dir = HERE / "runs" / time.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = server_fingerprint()

    results = {}
    for scenario in chosen:
        results[scenario["id"]] = []
        for i in range(1, args.repeats + 1):
            tag = f"{args.tag}-r{i}"
            for attempt in (1, 2):
                try:
                    rec = run_once(scenario, tag, fingerprint)
                    break
                except Exception as exc:  # retry once, then record the failure
                    print(f"{scenario['id']} {tag} attempt {attempt} failed: {exc!r}", file=sys.stderr)
                    rec = {"scenario": scenario["id"], "run": tag, "error": repr(exc)}
            (out_dir / f"{scenario['id']}-{tag}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2))
            results[scenario["id"]].append(rec)
            verdict = rec.get("verdict", {})
            print(scenario["id"], tag, verdict.get("result") if isinstance(verdict, dict) else "?", rec.get("error", ""))

    summary = summarize(results)
    (out_dir / f"summary-{args.tag}.json").write_text(json.dumps(
        {"tag": args.tag, "server": fingerprint, "scenarios": summary}, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    shutil.rmtree(WORKDIR, ignore_errors=True)


if __name__ == "__main__":
    main()
