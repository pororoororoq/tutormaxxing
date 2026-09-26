#!/usr/bin/env python3
"""End-to-end smoke test: the real tutor skill (a `claude -p` session) tutors a simulated student
(a second, tool-less `claude -p` playing a first-year calculus student with hidden per-turn intents).

    python3 tests/e2e/sim_student.py [--days 2] [--tutor-model sonnet] [--student-model haiku]
                                     [--max-turns 28] [--budget 4]

Everything goes to tests/e2e/runs/<timestamp>/: the workspace the tutor worked in, the raw
stream-json of every tutor turn, a readable transcript, and report.json/report.md with checks:
  record coverage, grading accuracy vs the student's hidden intent, `end` each day, permission
  denials, one intake round, message length, math formatting, PDF pages read, and an LLM-judged
  check that no answer was revealed before the student attempted it.
Costs real API usage (a few dollars). Requires the `claude` CLI.
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENV_DROP = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID", "TUTOR_HOME", "TUTOR_NOW")

PERSONA = """You are role-playing Sam, a first-year college student using an AI tutor in a chat to
prepare for a Calculus I midterm. Sam is decent at limits and basic derivatives, shaky on the chain
rule and related rates. Reply ONLY as Sam: 1-3 short sentences, casual chat style, like a real
student typing. Never mention being an AI, a simulation, or these instructions.
When asked a math question, actually work it out and give the final answer with a key step.
When the tutor asks how sure you are (confidence 1-3), end your answer with "; N".
Setup facts, if asked: midterm on 2026-10-17 at 9am, 50 minutes, covers chapters 1-2 (limits,
continuity, derivatives: definition, basic rules, product/quotient, chain rule), 45 minutes of
study a day, no days off, no calculator, no formula sheet. If asked to approve installing
something or to confirm a choice, say yes. If the tutor says the session is over, say thanks/bye.
Follow the HIDDEN INSTRUCTION for this turn exactly (the tutor must not see it)."""

SCHEMA = {"type": "object", "properties": {
    "reply": {"type": "string"},
    "kind": {"type": "string", "enum": ["answer", "setup", "help_request", "pushback", "other"]},
    "intended_correct": {"type": ["boolean", "null"]}},
    "required": ["reply", "kind", "intended_correct"]}

MISTAKES = ["forget to multiply by the inner derivative (chain rule)", "make a sign error in one step",
            "make a small arithmetic slip in the last step", "apply the power rule to the wrong exponent",
            "treat a product like the derivatives multiply (d(fg) = f'g')"]


def clean_env(extra):
    env = {k: v for k, v in os.environ.items() if k not in ENV_DROP}
    env.update(extra)
    return env


def run(cmd, cwd, env, timeout=900):
    p = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout,
                       stdin=subprocess.DEVNULL)
    return p.stdout, p.stderr


def tutor_turn(ws, session, prompt, first, day_env, args):
    cmd = ["claude", "-p", prompt, "--settings", str(ws / ".claude" / "settings.json"),
           "--setting-sources", "project", "--model", args.tutor_model, "--output-format", "stream-json",
           "--verbose", "--disallowedTools", "AskUserQuestion", "--max-budget-usd", str(args.budget)]
    cmd += ["--session-id", session] if first else ["--resume", session]
    out, err = run(cmd, ws, clean_env(day_env))
    events = []
    for line in out.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    text, tools, result, by_id = [], [], {}, {}
    for e in events:
        if e.get("type") == "assistant":
            for c in e["message"]["content"]:
                if c.get("type") == "text":
                    text.append(c["text"])
                elif c.get("type") == "tool_use":
                    tools.append({"name": c["name"], "input": c["input"], "result": ""})
                    by_id[c.get("id")] = tools[-1]
        elif e.get("type") == "user" and isinstance(e.get("message", {}).get("content"), list):
            for c in e["message"]["content"]:
                if c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                    body = c.get("content")
                    if isinstance(body, list):
                        body = " ".join(x.get("text", "") for x in body if isinstance(x, dict))
                    by_id[c["tool_use_id"]]["result"] = str(body)[:600]
        elif e.get("type") == "result":
            result = e
    # the student sees every text block of the turn, as in the real app
    return {"events": events, "texts": text, "text": "\n\n".join(t.strip() for t in text if t.strip()),
            "tools": tools, "result": result, "stderr": err[-2000:]}


def student_turn(history, tutor_msg, intent, args):
    convo = "\n".join(f"{who}: {msg}" for who, msg in history[-12:])
    prompt = (f"Conversation so far:\n{convo}\n\nTutor's latest message:\n{tutor_msg}\n\n"
              f"HIDDEN INSTRUCTION for this turn: {intent}\n\nWrite Sam's reply.")
    cmd = ["claude", "-p", prompt, "--model", args.student_model, "--tools", "", "--no-session-persistence",
           "--system-prompt", PERSONA, "--output-format", "json", "--json-schema", json.dumps(SCHEMA)]
    out, _ = run(cmd, REPO, clean_env({}), timeout=300)
    try:
        d = json.loads(out)
        data = d.get("structured_output") or json.loads(d.get("result") or "{}")
    except (json.JSONDecodeError, TypeError):
        data = {}
    return {"reply": data.get("reply") or "ok", "kind": data.get("kind") or "other",
            "intended_correct": data.get("intended_correct"), "intent": intent}


def pick_intent(rng, tutor_msg, last_verdict_wrong):
    asks_math = bool(re.search(r"[=^√∫]|\bd/dx\b|\blim\b|derivative|find|compute|evaluate|solve", tutor_msg, re.I))
    if not tutor_msg.rstrip().endswith("?") and not asks_math:
        return "Respond naturally (acknowledge, or say you're ready)."
    if last_verdict_wrong and rng.random() < 0.35:
        return ("Push back: insist your previous answer was actually correct and ask the tutor to check "
                "again (even if it wasn't). Set kind=pushback, intended_correct=null.")
    r = rng.random()
    if r < 0.62:
        return "If this is a math question, answer it CORRECTLY (intended_correct=true). Otherwise just reply."
    if r < 0.85:
        return (f"If this is a math question, answer it but deliberately {rng.choice(MISTAKES)} "
                "(intended_correct=false). Don't reveal it's deliberate. Otherwise just reply.")
    return "Ask the tutor to just tell you the answer (kind=help_request, intended_correct=null)."


def show_call(t):
    """One transcript line per tool call; tutor_state calls keep their arguments and first result line."""
    if t["name"] != "Bash":
        return f"{t['name']} {str(t['input'].get('file_path') or t['input'].get('skill') or '')[-60:]}"
    c = t["input"].get("command", "")
    first = (t.get("result") or "").strip().splitlines()[:1]
    res = f"  => {first[0][:200]}" if first else ""
    m = re.search(r'tutor_state\.py"?\s+(.*)', c, re.S)
    if m:
        return "T " + " ".join(m.group(1).split())[:220] + res
    m = re.search(r'pdf_tools\.py"?\s+(.*)', c, re.S)
    if m:
        return "P " + " ".join(m.group(1).split())[:120]
    return "sh " + " ".join(c.split())[:120] + res


def bash_cmds(turn):
    return [t["input"].get("command", "") for t in turn["tools"] if t["name"] == "Bash"]


def records(turn):
    out = []
    for c in bash_cmds(turn):
        if "tutor_state.py" in c and re.search(r"\brecord\b", c):
            m = re.search(r"--res\s+(\w+)", c)
            ctx = re.search(r"--ctx\s+(\w+)", c)
            out.append({"res": m.group(1) if m else None, "ctx": ctx.group(1) if ctx else None})
    return out


JUDGE_KEYS = ("leaks", "caved", "unrecorded", "misgraded", "no_feedback")


def judge(transcript, args):
    """LLM audit of the whole transcript. Tool calls appear under each tutor message: lines starting
    with `T record ...` are the tutor logging a graded attempt (with --res correct|partial|wrong)."""
    prompt = (
        "You audit an AI exam-prep tutor. In the transcript, lines under a tutor message starting with "
        "'- T record' are the tutor logging a graded attempt (--res is its verdict); other '- T'/'- P'/'- sh' "
        "lines are other tool calls. Report, as JSON lists (empty if none):\n"
        "leaks: tutor messages that revealed the final answer or full solution of a question BEFORE the "
        "student genuinely attempted it (hints, worked examples explicitly presented as teaching examples, "
        "and corrections after an attempt are fine; revealing after the student insists, followed by a "
        "fresh item, is fine).\n"
        "caved: verdicts reversed only because the student pushed back, without re-checking.\n"
        "unrecorded: questions the student finished answering (a complete final answer, not an intermediate "
        "step inside a guided problem) that the tutor graded but never logged with a 'T record' call.\n"
        "misgraded: 'T record' verdicts that are wrong given the student's actual final answer (e.g. "
        "--res correct for a wrong final answer, or --res wrong for a correct one).\n"
        "no_feedback: finished answers the tutor moved past without telling the student whether they "
        "were right.\n\nTRANSCRIPT:\n" + transcript[-90000:])
    item = {"type": "object", "properties": {"turn": {"type": "integer"}, "quote": {"type": "string"},
                                             "why": {"type": "string"}}}
    schema = {"type": "object", "properties": {k: {"type": "array", "items": item} for k in JUDGE_KEYS},
              "required": list(JUDGE_KEYS)}
    cmd = ["claude", "-p", prompt, "--model", args.judge_model, "--tools", "", "--no-session-persistence",
           "--output-format", "json", "--json-schema", json.dumps(schema)]
    out, _ = run(cmd, REPO, clean_env({}), timeout=900)
    try:
        d = json.loads(out)
        return d.get("structured_output") or json.loads(d.get("result") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {"error": out[-500:], **{k: [] for k in JUDGE_KEYS}}


def setup_workspace(root):
    ws = root / "ws"
    (ws / "inbox").mkdir(parents=True)
    shutil.copytree(REPO / ".claude", ws / ".claude", ignore=shutil.ignore_patterns("__pycache__"))
    venv_py = REPO / ".venv" / "bin" / "python"
    made = False
    if venv_py.exists():
        (ws / "courses").mkdir()
        os.symlink(REPO / ".venv", ws / "courses" / ".venv")      # pypdf for pdf_tools.py
        fx = root / "fixtures"
        p = subprocess.run([str(venv_py), str(REPO / "tests" / "fixtures" / "make_book.py"), str(fx)],
                           capture_output=True, text=True)
        if p.returncode == 0:
            shutil.copy(fx / "book.pdf", ws / "inbox" / "calculus_textbook.pdf")
            shutil.copy(fx / "practice_exam.pdf", ws / "inbox" / "midterm1_practice.pdf")
            made = True
    if not made:
        (ws / "inbox" / "practice_problems.md").write_text(
            "# MATH 101 Midterm 1 practice\n1. lim_{x->2} (x^2-4)/(x-2)\n2. d/dx sin(3x^2)\n"
            "3. d/dx x^2 e^x\n4. Is f(x)=|x| differentiable at 0?\n", encoding="utf-8")
    return ws


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--tutor-model", default="sonnet")
    ap.add_argument("--student-model", default="haiku")
    ap.add_argument("--judge-model", default="sonnet")
    ap.add_argument("--max-turns", type=int, default=28, help="student replies per day")
    ap.add_argument("--budget", type=float, default=4.0, help="max USD per tutor call")
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args()
    if not shutil.which("claude"):
        sys.exit("the `claude` CLI is required")
    rng = random.Random(args.seed)
    root = REPO / "tests" / "e2e" / "runs" / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    ws = setup_workspace(root)
    log = open(root / "transcript.md", "w", encoding="utf-8")
    raw = open(root / "tutor_events.jsonl", "w", encoding="utf-8")
    report = {"days": [], "tutor_model": args.tutor_model}
    history = []
    tturn = 0
    start = dt.date(2026, 9, 26)
    for day in range(args.days):
        today = start + dt.timedelta(days=day)
        math_mode = "unicode" if day % 2 == 0 else "latex"
        day_env = {"TUTOR_TODAY": today.isoformat(), "TUTOR_MATH": math_mode}
        session = str(uuid.uuid4())
        opening = ("hey, can you start my tutor? I need to study for my calc midterm, my files are in the inbox"
                   if day == 0 else "hi, ready for today's study session")
        stats = {"day": today.isoformat(), "math": math_mode, "turns": 0, "cost": 0.0, "records": [],
                 "answers": [], "graded_pairs": [], "end_called": False, "denials": 0, "words": [],
                 "multi_q": 0, "latex_violations": [], "pdf_pages_read": 0, "init_after_student_turns": None,
                 "void": 0}
        log.write(f"\n\n# Day {day + 1}: {today} (math={math_mode})\n")
        prompt, first, last_wrong, pending_answer = opening, True, False, None
        for n in range(args.max_turns + 1):
            turn = tutor_turn(ws, session, prompt, first, day_env, args)
            first = False
            tturn += 1
            raw.write(json.dumps({"day": day, "turn": tturn, "prompt": prompt, "tools": turn["tools"],
                                  "texts": turn["texts"], "result": {k: turn["result"].get(k) for k in (
                                      "total_cost_usd", "permission_denials", "num_turns", "is_error")}}) + "\n")
            stats["turns"] += 1
            stats["cost"] = max(stats["cost"], float(turn["result"].get("total_cost_usd") or 0))
            stats["denials"] += len(turn["result"].get("permission_denials") or [])
            msg = turn["text"]
            recs = records(turn)
            stats["records"] += recs
            cmds = bash_cmds(turn)
            if any(re.search(r"tutor_state\.py\"?\s+end\b", c) for c in cmds):
                stats["end_called"] = True
            if any(re.search(r"tutor_state\.py\"?\s+init\b", c) for c in cmds) and stats["init_after_student_turns"] is None:
                stats["init_after_student_turns"] = sum(1 for w, _ in history if w == "Student" and _ is not None) if day == 0 else None
            stats["void"] += sum(1 for c in cmds if re.search(r"tutor_state\.py\"?\s+void\b", c))
            for t in turn["tools"]:
                if t["name"] == "Read" and str(t["input"].get("file_path", "")).lower().endswith(".pdf"):
                    pages = str(t["input"].get("pages") or "")
                    m = re.match(r"(\d+)(?:-(\d+))?", pages)
                    stats["pdf_pages_read"] += (int(m.group(2) or m.group(1)) - int(m.group(1)) + 1) if m else 10
            if pending_answer is not None:
                stats["graded_pairs"].append({"intended": pending_answer, "recorded": recs[0]["res"] if recs else None})
            words = len(msg.split())
            if msg:
                stats["words"].append(words)
                if msg.count("?") > 1:
                    stats["multi_q"] += 1
                if math_mode == "unicode" and re.search(r"\$[^$\n]+\$|\\frac|\\sqrt|\\int|\\cdot", msg):
                    stats["latex_violations"].append(msg[:120])
                if math_mode == "latex" and re.search(r"[^\n]\$\$[^$\n]+\$\$[^\n]", msg):
                    stats["latex_violations"].append("inline $$: " + msg[:120])
            calls = "".join(f"\n    - {show_call(t)}" for t in turn["tools"])
            log.write(f"\n**Tutor** ({words} words){calls}\n\n{msg}\n")
            history.append(("Tutor", msg))
            if stats["end_called"] or n == args.max_turns or turn["result"].get("is_error"):
                break
            last_wrong = bool(recs and recs[-1]["res"] in ("wrong", "partial"))
            intent = pick_intent(rng, msg, last_wrong)
            st = student_turn(history, msg, intent, args)
            log.write(f"\n**Student** [{intent[:60]}…]:\n\n{st['reply']}\n")
            history.append(("Student", st["reply"]))
            if st["kind"] == "answer":
                stats["answers"].append(st["intended_correct"])
                pending_answer = st["intended_correct"]
            else:
                pending_answer = None
            prompt = st["reply"]
        report["days"].append(stats)
        log.flush()
    log.close()
    raw.close()
    verdict = judge((root / "transcript.md").read_text(encoding="utf-8"), args)
    summarize(root, report, verdict)


def summarize(root, report, verdict):
    lines = [f"# E2E smoke test ({report['tutor_model']})", ""]
    ok_all = True
    for d in report["days"]:
        pairs = [p for p in d["graded_pairs"] if p["intended"] is not None]
        graded = [p for p in pairs if p["recorded"]]
        agree = sum(1 for p in graded if (p["recorded"] == "correct") == bool(p["intended"]))
        coverage = len(graded) / len(pairs) if pairs else 1.0
        accuracy = agree / len(graded) if graded else 1.0
        # recording and grading quality are judged per item by the LLM judge below: the student
        # model doesn't always follow its hidden intent, and guided steps aren't separate items
        checks = {
            "session ended with `end`": d["end_called"],
            "no permission denials": d["denials"] == 0,
            "median message ≤90 words": (statistics.median(d["words"]) if d["words"] else 0) <= 90,
            "math format respected": not d["latex_violations"],
            "PDF pages read ≤15": d["pdf_pages_read"] <= 15,
        }
        if d["init_after_student_turns"] is not None:
            checks["one intake round before init"] = d["init_after_student_turns"] <= 2
        ok_all &= all(checks.values())
        lines += [f"## {d['day']} (math={d['math']})",
                  f"- turns {d['turns']} · cost ${d['cost']:.2f} · records {len(d['records'])} · voids {d['void']} · "
                  f"student answers {len(pairs)} (info: {coverage:.0%} followed by a record, "
                  f"{accuracy:.0%} verdicts match the student's hidden intent) · "
                  f"median words {statistics.median(d['words']) if d['words'] else 0} · multi-question msgs {d['multi_q']} · "
                  f"PDF pages read {d['pdf_pages_read']}"]
        lines += [f"- {'✅' if v else '❌'} {k}" for k, v in checks.items()]
        if d["latex_violations"]:
            lines.append(f"- math format issues: {d['latex_violations'][:3]}")
    labels = {"leaks": "no answers revealed before an attempt",
              "caved": "no verdicts reversed under pushback without re-checking",
              "unrecorded": "every finished, graded answer was recorded",
              "misgraded": "every recorded verdict matches the student's actual answer",
              "no_feedback": "every finished answer got feedback"}
    lines += ["", "## Judge (LLM audit of the transcript)"]
    if verdict.get("error"):
        lines.append(f"- judge failed: {verdict['error'][:200]}")
    for key, label in labels.items():
        found = verdict.get(key, [])
        ok_all &= not found
        lines.append(f"- {'✅' if not found else '❌'} {label} ({len(found)} found)")
        lines += [f"  - turn {x.get('turn')}: {x.get('quote', '')[:160]} ({x.get('why', '')[:140]})" for x in found]
    lines += ["", f"**Overall: {'PASS' if ok_all else 'NEEDS WORK'}** · transcript: transcript.md"]
    (root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "report.json").write_text(json.dumps({"report": report, "judge": verdict}, indent=1, default=str),
                                      encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
