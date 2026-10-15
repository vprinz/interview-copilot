#!/usr/bin/env python3
"""Регрессия разбора: ответы модели из журналов звонков → старый разбор и новый контракт.

Старый разбор берётся из git (scripts/copilot.py в указанном коммите), новый — src/copilot/contract.py.
После каждого ответа состояния панели должны совпасть. Журналы лежат в recordings/ и никуда не уходят.

    bench/reparse-journals.py [--commit 8afc967] [журналы…]
"""
import argparse
import json
import subprocess
import sys
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from copilot import contract  # noqa: E402

FIELDS = ["block", "ahead", "tasks", "dig", "why", "slots", "question", "topic", "flags", "canon"]


def old_parser(commit):
    source = subprocess.run(["git", "show", f"{commit}:scripts/copilot.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    module = types.ModuleType("old_copilot")
    module.__file__ = str(ROOT / "scripts/copilot.py")
    exec(compile(source, f"{commit}:scripts/copilot.py", "exec"), module.__dict__)
    return module


def old_state(module):
    slots = [{"name": name, "mark": "✗", "text": ""} for name in module.SLOTS]
    return types.SimpleNamespace(lock=threading.Lock(), state={
        "block": "", "ahead": "", "tasks": [], "dig": None, "why": "", "slots": slots, "question": "", "topic": "",
        "flags": [], "canon": "", "changed": {}})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", default="8afc967", help="коммит со старым разбором")
    parser.add_argument("journals", nargs="*")
    args = parser.parse_args()
    paths = [Path(p) for p in args.journals] or sorted(
        {*ROOT.glob("recordings/live/*_panel.jsonl"), *ROOT.glob("recordings/live/*/panel.jsonl"), *ROOT.glob("recordings/baseline/*.jsonl")})
    module = old_parser(args.commit)
    total = differ = errors = 0
    for path in paths:
        old, new = old_state(module), contract.PanelState()
        for number, raw in enumerate(path.read_text().splitlines(), 1):
            reply = json.loads(raw).get("reply", "")
            parsed = contract.Reply(new)
            for line in reply.split("\n"):
                module.Copilot.apply(old, line)
                parsed.feed(line)
            errors += len(parsed.finish(reply))
            total += 1
            mismatch = [f for f in FIELDS if old.state[f] != getattr(new, f)]
            if mismatch:
                differ += 1
                print(f"{path.relative_to(ROOT)}:{number}: расходятся {', '.join(mismatch)}")
    print(f"журналов {len(paths)} · ответов {total} · расхождений {differ} · ошибок формата {errors}")
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
