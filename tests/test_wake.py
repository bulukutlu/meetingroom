import asyncio, tempfile
from pathlib import Path
from meetingroom.agents import expand_agents
from meetingroom.server import Room, MAX_HOPS, MAX_HOPS_SUPERVISED

BASE = [dict(name="claude", provider="mock", model="opus", color="#d97757")]


def test_limits():
    assert MAX_HOPS == 4 and MAX_HOPS_SUPERVISED == 10


def test_wake_on_file_and_say_now():
    async def go():
        ws = tempfile.mkdtemp()
        r = Room({"agents": expand_agents(BASE, ["claude"]), "catalog": BASE, "workspace": ws, "user_name": "U"})
        async def bc(ev): pass
        r.broadcast = bc
        a = r.agents["claude"]
        flag = Path(ws) / "done.flag"
        assert "error" in await r.wake_me(a, {"note": "x"})
        assert (await r.wake_me(a, {"note": "check fit", "file_exists": str(flag)})).startswith("ok")
        assert "posted" in await r.say_now(a, "halfway there")
        flag.write_text("1")
        import meetingroom.server as s
        orig = asyncio.sleep
        async def fast(t): await orig(0.01)
        s.asyncio.sleep = fast
        try:
            await orig(0.2)
        finally:
            s.asyncio.sleep = orig
        assert a.wake_notes and "check fit" in a.wake_notes[0] and not r.wakers
        for t in r.tasks: t.cancel()
    asyncio.run(go())
