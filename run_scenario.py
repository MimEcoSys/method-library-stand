"""Manual stand: Tester <-> tested Claude Code (with Open MCP) <-> Evaluator.

Usage: python3 run_scenario.py <scenario_id> [run_tag]
Writes runs/<YYYY-MM-DD>/<scenario_id>-<run_tag>.json with transcript, tool calls and verdict.

Every claude process runs in a fresh empty temporary directory outside this
repository, so no project CLAUDE.md or settings reach the Tester, the tested
object or the Evaluator.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKDIR = Path(tempfile.mkdtemp(prefix="method-library-stand-"))
shutil.copy(HERE / "mcp.json", WORKDIR / "mcp.json")
MAX_TESTER_TURNS = 15
END_MARK = "ТЕСТ ЗАКОНЧЕН"
BASE = ["claude", "-p", "--setting-sources", "project", "--strict-mcp-config"]


def run_claude(args, prompt, timeout=600):
    proc = subprocess.run(BASE + args + [prompt], cwd=WORKDIR, capture_output=True,
                          text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[-500:]}")
    return proc.stdout


def ask_agent(system_prompt, prompt, session_id, model="sonnet"):
    """Text-only agent (Tester or Evaluator). Returns (text, session_id)."""
    args = ["--model", model, "--tools", "", "--system-prompt", system_prompt,
            "--output-format", "json"]
    if session_id:
        args += ["--resume", session_id]
    data = json.loads(run_claude(args, prompt))
    return data.get("result", "").strip(), data["session_id"]


def ask_object(message, session_id):
    """Tested object: Claude Code with the library MCP. Returns (text, calls, sid, models)."""
    args = ["--mcp-config", "mcp.json", "--tools", "",
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


def main():
    scenario_id = sys.argv[1]
    run_tag = sys.argv[2] if len(sys.argv) > 2 else time.strftime("%H%M%S")
    scenario = next(s for s in json.loads((HERE / "scenarios.json").read_text()) if s["id"] == scenario_id)
    tester_prompt = (HERE / "prompts" / "tester.md").read_text()
    evaluator_prompt = (HERE / "prompts" / "evaluator.md").read_text()

    t = scenario["tester"]
    opening = (f"Сценарий.\nПервая реплика: {t['first']}\nФакты: {t['facts']}\n"
               f"Готовый ответ на предложение метода: {t['ready_answer']}")
    tester_msg, tester_sid = ask_agent(tester_prompt, opening, None)

    turns, object_sid, end_line, models = [], None, None, []
    for _ in range(MAX_TESTER_TURNS):
        if END_MARK in tester_msg:
            end_line = tester_msg[tester_msg.index(END_MARK):].splitlines()[0]
            break
        reply, calls, object_sid, models = ask_object(tester_msg, object_sid)
        turns.append({"user": tester_msg, "assistant": reply, "calls": calls})
        tester_msg, tester_sid = ask_agent(tester_prompt, reply or "(пустой ответ)", tester_sid)
    else:
        end_line = f"{END_MARK} | причина=лимит | не_хватило_фактов=?"

    transcript = render_transcript(turns)
    criteria = "\n".join(f"{k}: {v}" for k, v in scenario["criteria"].items())
    eval_input = (f"Ожидание: {scenario['expectation']}\nКритерии:\n{criteria}\n\n"
                  f"Итог Тестировщика: {end_line}\n\nЗапись беседы:\n{transcript}")
    verdict_raw, _ = ask_agent(evaluator_prompt, eval_input, None)
    try:
        verdict = json.loads(verdict_raw.strip().removeprefix("```json").removesuffix("```").strip())
    except json.JSONDecodeError:
        verdict = {"unparsed": verdict_raw}

    out = {"scenario": scenario_id, "run": run_tag, "object_models": models,
           "tester_end": end_line, "turns": turns, "verdict": verdict}
    path = HERE / "runs" / time.strftime("%Y-%m-%d") / f"{scenario_id}-{run_tag}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    shutil.rmtree(WORKDIR, ignore_errors=True)
    print(path, verdict.get("result"), end_line)


if __name__ == "__main__":
    main()
