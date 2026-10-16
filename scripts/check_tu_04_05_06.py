"""Checks BE-TU-04 (timeline), BE-TU-05 (chatbot) and BE-TU-06 (chat API) on the seeded demo meeting.

    set BACKEND_URL=http://127.0.0.1:8000
    set TEACHER_EMAIL=... & set TEACHER_PASSWORD=... & set MEETING_ID=<from seed_demo_timeline.py>
    (optional) set STUDENT_EMAIL=... & set STUDENT_PASSWORD=...   # adds the permission checks
    python scripts/check_tu_04_05_06.py

Expected values are the segments in scripts/seed_demo_timeline.py:
  0-10 neutral | 10-25 happy | 25-30 no_face | 30-45 sad | 45-52 angry | 52-60 neutral
"""

import os
import sys

import httpx

BACKEND = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
results = []
sys.stdout.reconfigure(encoding="utf-8")


def check(test_id, name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {test_id} {name}" + (f" -- {detail}" if detail else ""))


def login(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        sys.exit(f"login failed for {email}: {r.status_code} {r.text[:120]}")
    return {"Authorization": "Bearer " + r.json()["data"]["access_token"]}


def spans(refs):
    return [(r["start_seconds"], r["end_seconds"], r["emotion"]) for r in refs]


def main():
    c = httpx.Client(base_url=BACKEND, timeout=60)
    meeting = os.environ["MEETING_ID"]
    teacher = login(c, os.environ["TEACHER_EMAIL"], os.environ["TEACHER_PASSWORD"])
    timeline = f"/meetings/{meeting}/emotions/timeline"
    chat = f"/meetings/{meeting}/chat"

    def ask(question, **extra):
        return c.post(chat, json={"question": question, **extra}, headers=teacher)

    # ---------------------------------------------------------------- BE-TU-04 timeline
    r = c.get(timeline, headers=teacher)
    t = r.json()["data"] if r.status_code == 200 else {}
    segs = t.get("segments", [])
    check("TU-04", "full timeline returns 6 ordered [start,end) segments, 60 s",
          r.status_code == 200 and len(segs) == 6 and t["duration_seconds"] == 60
          and spans(segs)[1] == (10, 25, "happy") and spans(segs)[2] == (25, 30, "no_face"),
          f"{r.status_code} {len(segs)} segments")
    check("TU-04", "segments touch end-to-start without overlap",
          all(a["end_seconds"] == b["start_seconds"] for a, b in zip(segs, segs[1:])))
    s = t.get("summary", {})
    check("TU-04", "summary: analysed 55 s, no_face 5 s, coverage 0.9167, dominant neutral",
          s.get("analyzed_seconds") == 55 and s.get("no_face_seconds") == 5
          and s.get("coverage") == 0.9167 and s.get("dominant_emotion") == "neutral", str(s.get("coverage")))
    check("TU-04", "percentages use analysed time only (neutral 18 s = 32.73%)",
          s.get("emotions", {}).get("neutral") == {"seconds": 18.0, "percent": 32.73})
    check("TU-04", "no_face is never counted as an emotion", "no_face" not in s.get("emotions", {}))
    check("TU-04", "model_version and data_status present",
          t.get("model_version") == "demo-seed" and t.get("data_status") == "COMPLETED")
    r = c.get(timeline, params={"from_seconds": 20, "to_seconds": 40}, headers=teacher)
    w = r.json()["data"]["segments"] if r.status_code == 200 else []
    check("TU-04", "range 20-40 clips segments to the range",
          spans(w) == [(20, 25, "happy"), (25, 30, "no_face"), (30, 40, "sad")], str(spans(w)))
    r = c.get(timeline, params={"from_seconds": 40, "to_seconds": 20}, headers=teacher)
    check("TU-04", "from >= to is rejected (422)", r.status_code == 422, str(r.status_code))
    r = c.get(timeline, params={"recording_id": "does-not-exist"}, headers=teacher)
    check("TU-04", "unknown recording_id -> 404 RECORDING_NOT_FOUND", r.status_code == 404, str(r.status_code))
    r = c.get("/meetings/does-not-exist/emotions/timeline", headers=teacher)
    check("TU-04", "unknown meeting -> 404", r.status_code == 404, str(r.status_code))
    check("TU-04", "no token -> 401", c.get(timeline).status_code == 401)

    # ---------------------------------------------------------------- BE-TU-05 chatbot
    r = ask("Từ 00:20 đến 00:40 học sinh có cảm xúc gì?")
    d = r.json()["data"]
    check("TU-05", "GET_EMOTION_BY_TIME 00:20-00:40 -> happy 5 s, no_face 5 s, sad 10 s",
          r.status_code == 200 and d["intent"] == "GET_EMOTION_BY_TIME"
          and spans(d["references"]) == [(20, 25, "happy"), (25, 30, "no_face"), (30, 40, "sad")]
          and "5 giây" in d["answer"] and "10 giây" in d["answer"], d["answer"][:110])
    r = ask("Cảm xúc buồn xuất hiện trong khoảng nào?")
    d = r.json()["data"]
    check("TU-05", "FIND_EMOTION sad -> [30,45)", d["intent"] == "FIND_EMOTION"
          and spans(d["references"]) == [(30, 45, "sad")] and "00:30–00:45" in d["answer"], d["answer"][:110])
    r = ask("Khi nào học sinh vui?")
    d = r.json()["data"]
    check("TU-05", "FIND_EMOTION happy -> [10,25)", spans(d["references"]) == [(10, 25, "happy")], d["answer"][:90])
    r = ask("Khi nào học sinh giận?")
    d = r.json()["data"]
    check("TU-05", "Vietnamese 'giận' maps to angry -> [45,52)",
          spans(d["references"]) == [(45, 52, "angry")], d["answer"][:90])
    r = ask("Khi nào bình thường?")
    d = r.json()["data"]
    check("TU-05", "neutral appears in two separate spans",
          spans(d["references"]) == [(0, 10, "neutral"), (52, 60, "neutral")], d["answer"][:90])
    r = ask("Học sinh có sợ hãi lúc nào không?")
    d = r.json()["data"]
    check("TU-05", "emotion that never occurred -> no invented span",
          d["references"] == [] and "Không ghi nhận" in d["answer"], d["answer"][:90])
    r = ask("Từ 00:00 đến 00:30 học sinh có buồn không?")
    d = r.json()["data"]
    check("TU-05", "bounded FIND_EMOTION respects the asked range (no sad in 0-30)",
          d["intent"] == "FIND_EMOTION" and d["references"] == [], d["answer"][:90])
    r = ask("Lúc 00:15 học sinh thế nào?")
    d = r.json()["data"]
    check("TU-05", "single moment 00:15 -> happy", "vui vẻ" in d["answer"] and spans(d["references"])[0][2] == "happy", d["answer"][:90])
    r = ask("Từ 1:00 đến 3:00 có gì?")
    d = r.json()["data"]
    check("TU-05", "range starting at the end of the video is reported as outside it",
          d["references"] == [] and "ngoài video" in d["answer"], d["answer"][:90])
    check("TU-05", "every answer states parser rules|llm and data_status COMPLETED",
          d["parser"] in {"rules", "llm"} and d["data_status"] == "COMPLETED")

    # ---------------------------------------------------------------- BE-TU-06 chat API
    r = ask("Hôm nay trời đẹp không?")
    d = r.json()["data"]
    check("TU-06", "out-of-scope question -> UNKNOWN with guidance, no references",
          r.status_code == 200 and d["intent"] == "UNKNOWN" and d["references"] == [], f"parser={d['parser']}")
    r = ask("   ")
    check("TU-06", "blank question -> 422", r.status_code == 422, str(r.status_code))
    r = ask("a" * 501)
    check("TU-06", "question over 500 chars -> 422", r.status_code == 422, str(r.status_code))
    r = c.post(chat, json={}, headers=teacher)
    check("TU-06", "missing question -> 422", r.status_code == 422, str(r.status_code))
    r = ask("Khi nào buồn?", recording_id="nope")
    check("TU-06", "unknown recording_id -> 404", r.status_code == 404, str(r.status_code))
    check("TU-06", "no token -> 401", c.post(chat, json={"question": "x"}).status_code == 401)
    r = c.post("/meetings/does-not-exist/chat", json={"question": "x"}, headers=teacher)
    check("TU-06", "unknown meeting -> 404", r.status_code == 404, str(r.status_code))
    r = ask("Em học sinh có lúc nào khóc không?")
    d = r.json()["data"]
    print(f"[INFO] TU-05 paraphrase 'khóc' -> intent={d['intent']} parser={d['parser']} refs={spans(d['references'])}"
          " (parser=llm means Gemini understood a question the rules did not)")

    if os.getenv("STUDENT_EMAIL"):
        student = login(c, os.environ["STUDENT_EMAIL"], os.environ["STUDENT_PASSWORD"])
        check("T10", "student cannot read the timeline (403)", c.get(timeline, headers=student).status_code == 403)
        check("T10", "student cannot use the chat (403)",
              c.post(chat, json={"question": "x"}, headers=student).status_code == 403)

    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
