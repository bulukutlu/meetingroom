import asyncio, yaml, pathlib, tempfile
from meetingroom.agents import expand_agents
from meetingroom.server import Room

BASE = [dict(name="claude", provider="mock", model="opus", color="#d97757"),
        dict(name="sonnet", provider="mock", model="sonnet", color="#6a8fd8")]

def test_add_remove():
    async def go():
        ws = tempfile.mkdtemp()
        specs = expand_agents(BASE, ["claude", "sonnet"])
        r = Room({"agents": specs, "catalog": BASE, "workspace": ws, "user_name": "U"})
        sent = []
        async def bc(ev): sent.append(ev["type"])
        r.broadcast = bc
        assert await r.add_agent("sonnet") == ""
        assert "sonnet-2" in r.agents and r.agents["sonnet-2"].person.lower() in r.alias
        assert r.tts.voices["sonnet-2"]
        assert await r.remove_agent("sonnet-2") == ""
        assert "sonnet-2" not in r.agents and "sonnet-2" not in r.tts.voices
        for _ in range(3): assert await r.add_agent("claude") == ""
        assert "no free seat" in (await r.add_agent("claude")).lower()
        assert "roster" in sent
        for t in r.tasks: t.cancel()
    asyncio.run(go())
