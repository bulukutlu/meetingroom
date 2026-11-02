import asyncio, types
from meetingroom.server import Room

def test_progress_flow():
    r = Room.__new__(Room); r.progress = {}; r.sent = []
    async def bc(ev): r.sent.append(ev["type"])
    r.broadcast = bc
    a = types.SimpleNamespace(name="sonnet")
    run = asyncio.run
    run(r.report_progress(a, {"task": "Scan", "step": 1, "steps": 4, "stage": "load", "eta_minutes": 12}))
    assert r.progress["sonnet|scan"]["percent"] == 25
    run(r.report_progress(a, {"task": "Scan", "percent": 100}))
    assert not r.progress and r.sent == ["progress", "progress_done"]
    run(r.report_progress(a, {"task": "X", "percent": 40})); run(r.clear_progress(a))
    assert not r.progress
