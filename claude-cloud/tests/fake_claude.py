#!/usr/bin/env python3
"""A stand-in for ``claude --cloud``, and for the cloud session it starts.

As the engine runs it, it logs its arguments, then starts the "cloud session" in a process of
its own and ends. That process runs the real tincan hook as Claude Code would: the prompt,
a tool call, then the stop, with the reply ``reply to: <prompt>``.

    FAKE_CLOUD   a folder: calls.jsonl, and a home per cloud session
    FAKE_HOOK    the hook that environment/setup.sh installed
    FAKE_MODE    normal; silent: the session takes the prompt and never answers;
                 deaf: it never takes the prompt; refuse: claude exits 1
    TINCAN_URL   the tincan repository
"""

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(os.environ["FAKE_CLOUD"])
MODE = os.environ.get("FAKE_MODE", "normal")


def hook(session: str, name: str, event: dict) -> None:
    home = ROOT / session
    home.mkdir(parents=True, exist_ok=True)
    env = dict(
        os.environ,
        CLAUDE_CODE_REMOTE="true",
        CLAUDE_CODE_REMOTE_SESSION_ID=session,
        TINCAN_HOME=str(home),
    )
    subprocess.run(
        [sys.executable, os.environ["FAKE_HOOK"], name],
        input=json.dumps(event),
        text=True,
        env=env,
        check=True,
    )


def cloud_side(session: str, message: str) -> None:
    if MODE == "deaf":
        return
    hook(session, "prompt", {"prompt": message})
    time.sleep(0.2)
    hook(session, "post-tool", {})
    if MODE == "silent":
        return
    time.sleep(0.2)
    text = message.split("\n", 1)[1].split("\n\n<instructions>", 1)[0]
    hook(
        session, "stop", {"last_assistant_message": f"reply to: {text}", "stop_hook_active": False}
    )


def main(args: list[str]) -> int:
    if args[0] == "--cloud-side":
        cloud_side(args[1], args[2])
        return 0
    ROOT.mkdir(parents=True, exist_ok=True)
    with open(ROOT / "calls.jsonl", "a") as calls:
        calls.write(json.dumps({"args": args, "cwd": os.getcwd()}) + "\n")
    if MODE == "refuse":
        print("not signed in", file=sys.stderr)
        return 1
    cloud = args.index("--cloud")
    # claude -p <message> --cloud <session>, or claude -p --cloud <message> for a new one.
    if args[1] == "--cloud":
        session, message = "cse_" + uuid.uuid4().hex, args[cloud + 1]
        answer = None
    else:
        session, message = args[cloud + 1], args[1]
        answer = {"ok": True, "session_id": session, "url": f"https://claude.ai/code/{session}"}
    subprocess.Popen(
        [sys.executable, __file__, "--cloud-side", session, message],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
    )
    if answer:
        print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
