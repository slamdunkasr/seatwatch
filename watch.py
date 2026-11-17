"""Seat watch: checks CSUF's public class search and pings your phone (ntfy) when a watched
section opens up. Runs from GitHub Actions in a loop, checking every ~2 minutes."""
import json, os, sys, time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import requests, yaml

sys.path.insert(0, str(Path(__file__).parent))
import csuf
import snap

ROOT = Path(__file__).parent
STATE = ROOT / "state.json"
INTERVAL = int(os.environ.get("INTERVAL_SEC", "120"))
LOOP_MIN = int(os.environ.get("LOOP_MINUTES", "0"))
GOOD = ("open", "wait list", "waitlist")
HEARTBEAT_SEC = int(os.environ.get("HEARTBEAT_HOURS", "4")) * 3600
PRIORITY = {"max": 5, "high": 4, "default": 3, "low": 2}


def _hdr(v):
    v = str(v)
    if v.isascii():
        return v
    import base64
    return "=?UTF-8?B?" + base64.b64encode(v.encode()).decode() + "?="


def push(title, msg, priority="high", tags=("rotating_light",), click=None, image=None):
    topic = os.environ.get("NTFY_TOPIC")
    print(f"PUSH: {title} | {msg}" + (" [+image]" if image else ""))
    if not topic:
        return
    if image:
        # File upload: the PNG is the body, everything else rides in headers (\n = line break).
        headers = {"Title": _hdr(title), "Message": _hdr(msg.replace("\n", "\\n")),
                   "Priority": str(PRIORITY.get(priority, 4)), "Tags": ",".join(tags),
                   "Filename": "csuf-class-search.png"}
        if click:
            headers["Click"] = click
        try:
            r = requests.put(f"https://ntfy.sh/{topic}", data=image, headers=headers, timeout=30)
            if r.ok:
                return
            print("image push failed:", r.status_code, r.text[:200])
        except Exception as e:
            print("image push failed:", e)
    payload = {"topic": topic, "title": title, "message": msg, "priority": PRIORITY.get(priority, 4),
               "tags": list(tags)}
    if click:
        payload["click"] = click
    try:
        requests.post("https://ntfy.sh/", json=payload, timeout=20)
    except Exception as e:
        print("push failed:", e)


def check_once():
    cfg = yaml.safe_load((ROOT / "watch.yaml").read_text())
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    first = not any(k != "_meta" for k in state)
    need_save = first
    seen = []
    pages = []  # (result_html, watched class numbers) for notification snapshots
    for c in cfg["classes"]:
        dbg = {}
        try:
            res = csuf.search(cfg["term"], c["subject"], str(c["catalog"]), debug=dbg)
        except Exception as e:
            print(f"search failed for {c['subject']} {c['catalog']}: {e}")
            continue
        if not res:
            print(f"no sections returned for {c['subject']} {c['catalog']} (site change or outage?)")
            continue
        want = set(c.get("sections") or res.keys())
        page = (dbg.get("result_html"), sorted(want))
        pages.append(page)
        for nbr, info in res.items():
            if nbr not in want:
                continue
            status = info["status"]
            prev = state.get(nbr, {}).get("status")
            name = f"{c['subject']} {c['catalog']} sec {info['section'].split('-')[0]} (#{nbr})"
            print(f"{name}: {status} (was {prev})")
            seen.append((name, status))
            if prev != status:
                need_save = True
            if first or prev is None:
                push(f"Seat watch on: {name}", f"Now watching. Current status: {status}. "
                     "You'll get an alert when it opens.", priority="default", tags=("eyes",),
                     click=csuf.URL, image=snap.render([page]))
            elif status.lower() in GOOD and (prev or "").lower() not in GOOD:
                push(f"OPEN: {name}", f"Status changed {prev} -> {status}. Enroll now in Titan Online!",
                     priority="max", click="https://my.fullerton.edu", image=snap.render([page]))
            elif prev and prev.lower() in GOOD and status.lower() not in GOOD:
                push(f"Closed again: {name}", f"Status changed {prev} -> {status}.",
                     priority="default", tags=("x",), image=snap.render([page]))
            state[nbr] = {"status": status, "name": name, "t": int(time.time())}
    # Heartbeat: every few hours, say what the latest check found so you know it's still running.
    meta = state.setdefault("_meta", {})
    now = time.time()
    if seen and not first and now - meta.get("heartbeat", 0) >= HEARTBEAT_SEC:
        when = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%-I:%M %p")
        lines = [f"{n}: {s}" for n, s in seen]
        still_closed = all(s.lower() not in GOOD for _, s in seen)
        title = "Still closed, still checking" if still_closed else "Seat watch: a section is OPEN"
        tail = ("Checking every 2 min; you'll get an instant alert if it opens." if still_closed
                else "Enroll now in Titan Online!")
        push(title, "\n".join(lines) + f"\nChecked at {when}. {tail}",
             priority="default" if still_closed else "max", tags=("hourglass",) if still_closed else ("rotating_light",),
             click=csuf.URL if still_closed else "https://my.fullerton.edu", image=snap.render(pages))
        meta["heartbeat"] = int(now)
        need_save = True
    elif first:
        meta["heartbeat"] = int(now)
    if "--test" in sys.argv:
        when = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%-I:%M %p")
        push("TEST: Seat watch with snapshot", "\n".join(f"{n}: {s}" for n, s in seen) +
             f"\nLive check at {when}. Your sections are highlighted in the image.",
             priority="high", tags=("camera",), click=csuf.URL, image=snap.render(pages))
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True))
    return need_save


def save():
    """Commit state.json so the next run remembers statuses (only when it changed)."""
    os.system('git add state.json && (git diff --cached --quiet || (git commit -qm "seatwatch: update" '
              '&& git pull -q --rebase -X theirs && git push -q))')


def main():
    if not LOOP_MIN:
        if check_once():
            save()
        return
    end = time.time() + LOOP_MIN * 60
    while True:
        try:
            need_save = check_once()
        except Exception as e:
            print("check failed:", e)
            need_save = False
        sys.argv = [a for a in sys.argv if a != "--test"]
        if need_save:
            save()
        if time.time() + INTERVAL > end:
            break
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
