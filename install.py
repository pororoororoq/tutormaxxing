#!/usr/bin/env python3
"""Make the tutor skill available in every Claude Code session on this computer.

    python3 install.py                  # link it: `git pull` in this repo then updates it everywhere
    python3 install.py --copy           # copy instead (if linking fails, e.g. some Windows setups)
    python3 install.py --allow-python   # also let Claude run any python3 command without asking
    python3 install.py --uninstall      # undo everything this script did

What it does:
1. Puts the skill at ~/.claude/skills/tutor as a link back to this repo's .claude/skills/tutor,
   so this repo stays the one copy you improve.
2. Adds user-level permission rules to ~/.claude/settings.json (backed up first), so a study
   session in any folder doesn't stop for approval prompts:
     Skill(tutor), Skill(tutor *)       Claude may load the tutor in any project
     Edit(courses/**)                    the tutor may write its files in the folder you study in
     Bash(python3 "<skill>/scripts/*)    the tutor may run its own scripts
   The tutor also checks answers with short `python3 -c` computations. Those still ask first unless
   you pass --allow-python (adds Bash(python3 *) for all projects) or use Auto permission mode.

Respects $CLAUDE_CONFIG_DIR. Python 3.9+, standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path

NAME = "tutor"
REPO = Path(__file__).resolve().parent
SRC = REPO / ".claude" / "skills" / NAME
MARKER = "tutor-install.json"          # remembers what this script added, for --uninstall


def config_dir():
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def stamp():
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def say(msg):
    print(msg, flush=True)


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def rules_for(skill_dirs, allow_python):
    """Permission rules the tutor needs. Script rules are written for every path Claude might use
    for the skill folder (the link and its target), with and without quotes, for python3 and python."""
    rules = ["Skill(tutor)", "Skill(tutor *)", "Edit(courses/**)"]
    for d in skill_dirs:
        prefix = f"{d}/scripts/"               # SKILL.md builds commands as "${CLAUDE_SKILL_DIR}/scripts/…"
        for py in ("python3", "python"):
            rules += [f'Bash({py} "{prefix}*)', f"Bash({py} {prefix}*)"]
    if allow_python:
        rules += ["Bash(python3 *)", "Bash(python *)"]
    seen, out = set(), []
    for r in rules:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def load_json(path):
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        fail(f"{path} isn't valid JSON ({e}). Fix it, or re-run with --no-permissions.")
    if not isinstance(data, dict):
        fail(f"{path} should contain a JSON object. Fix it, or re-run with --no-permissions.")
    return data


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def is_our_copy(path):
    """A real folder that holds this tutor skill (so it's safe to replace or remove)."""
    skill = path / "SKILL.md"
    if not (skill.is_file() and (path / "scripts" / "tutor_state.py").is_file()):
        return False
    head = skill.read_text(encoding="utf-8", errors="replace")[:400]
    return "\nname: tutor\n" in head.replace("\r\n", "\n")


def clear_dest(dest, force, keep_same_link):
    """Make room at dest. Returns "same" when it already links to this repo (and that's wanted),
    otherwise a short note about what was replaced, or None if dest was free."""
    if dest.is_symlink():
        if dest.resolve() == SRC.resolve():
            if keep_same_link:
                return "same"
            dest.unlink()
            return "replaced the link with a copy"
        if not force:
            fail(f"{dest} links to {os.readlink(dest)}, not to this repo. Re-run with --force to replace it.")
        dest.unlink()
        return "replaced a link to another folder"
    if dest.exists():
        if is_our_copy(dest):
            shutil.rmtree(dest)                   # an older copy of this same tutor: the repo is the source
            return "replaced the previous copy"
        if not force:
            fail(f"{dest} already exists and isn't this tutor. Re-run with --force to replace it "
                 "(it's moved to ~/.claude/skill-backups first).")
        backup = config_dir() / "skill-backups" / f"{NAME}-{stamp()}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dest), str(backup))       # outside skills/, so Claude doesn't load two tutors
        return f"moved the old folder to {backup}"
    return None


def install(args):
    if not (SRC / "SKILL.md").is_file():
        fail(f"can't find {SRC / 'SKILL.md'}: run install.py from the tutormaxxing repo")
    if sys.version_info < (3, 9):
        say(f"warning: the tutor needs Python 3.9+; this is {sys.version.split()[0]}")
    cfg = config_dir()
    dest = cfg / "skills" / NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    before = clear_dest(dest, args.force, keep_same_link=not args.copy)
    mode = "link"
    if before == "same":
        say(f"✓ already linked: {dest} → {SRC}")
    else:
        if before:
            say(f"  ({before})")
        linked = False
        if not args.copy:
            try:
                os.symlink(SRC, dest, target_is_directory=True)
                linked = True
            except (OSError, NotImplementedError) as e:
                say(f"  couldn't create a link ({e}); copying instead")
        if not linked:
            shutil.copytree(SRC, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            mode = "copy"
        say(f"✓ tutor installed for every Claude Code session: {dest}" +
            (f" → {SRC}" if mode == "link" else " (a copy)"))
    marker = cfg / MARKER
    state = load_json(marker)
    added = list(state.get("rules") or [])
    if not args.no_permissions:
        settings = cfg / "settings.json"
        data = load_json(settings)
        allow = data.setdefault("permissions", {}).setdefault("allow", [])
        if not isinstance(allow, list):
            fail(f"permissions.allow in {settings} isn't a list; fix it or re-run with --no-permissions")
        new = [r for r in rules_for([dest, SRC], args.allow_python) if r not in allow]
        if new:
            if settings.is_file():
                shutil.copy2(settings, settings.with_name(f"settings.json.bak-{stamp()}"))
            allow.extend(new)
            write_json(settings, data)
            added += [r for r in new if r not in added]
            say(f"✓ added {len(new)} permission rule(s) to {settings} (backup saved next to it)")
        else:
            say(f"✓ permission rules already present in {settings}")
    write_json(marker, {"dest": str(dest), "source": str(SRC), "mode": mode, "rules": added,
                        "installed": dt.datetime.now().isoformat(timespec="seconds")})
    say("")
    say("Next: start a NEW Claude Code session in any folder (e.g. one for your course),")
    say("put your PDFs in an inbox/ folder there, and type /tutor.")
    if mode == "link":
        say(f"Update later with:  git -C \"{REPO}\" pull")
    else:
        say("This is a copy: after `git pull`, run install.py again to update it.")
    if not args.allow_python and not args.no_permissions:
        say("Tip: answer checks (python3 -c …) still ask for approval. Use Auto mode, or re-run with --allow-python.")
    return 0


def uninstall(args):
    cfg = config_dir()
    dest = cfg / "skills" / NAME
    state = load_json(cfg / MARKER)
    if dest.is_symlink():
        if dest.resolve() != SRC.resolve() and not args.force:
            fail(f"{dest} links somewhere else ({os.readlink(dest)}); not touching it without --force")
        dest.unlink()
        say(f"✓ removed {dest}")
    elif dest.exists():
        if not is_our_copy(dest) and not args.force:
            fail(f"{dest} isn't this tutor; not removing it without --force")
        shutil.rmtree(dest)
        say(f"✓ removed {dest}")
    else:
        say(f"  nothing at {dest}")
    ours = set(state.get("rules") or [])
    settings = cfg / "settings.json"
    if ours and settings.is_file():
        data = load_json(settings)
        allow = data.get("permissions", {}).get("allow", [])
        kept = [r for r in allow if r not in ours]
        if len(kept) != len(allow):
            shutil.copy2(settings, settings.with_name(f"settings.json.bak-{stamp()}"))
            data["permissions"]["allow"] = kept
            write_json(settings, data)
            say(f"✓ removed {len(allow) - len(kept)} permission rule(s) this installer had added")
    marker = cfg / MARKER
    if marker.is_file():
        marker.unlink()
    say("Your study folders (courses/…) were not touched.")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--copy", action="store_true", help="copy the skill instead of linking it")
    ap.add_argument("--allow-python", action="store_true",
                    help="also allow any python3/python command without asking (all projects)")
    ap.add_argument("--no-permissions", action="store_true", help="don't touch settings.json")
    ap.add_argument("--force", action="store_true", help="replace an existing, different tutor install")
    ap.add_argument("--uninstall", action="store_true", help="remove the skill and the rules this script added")
    args = ap.parse_args(argv)
    return uninstall(args) if args.uninstall else install(args)


if __name__ == "__main__":
    sys.exit(main())
