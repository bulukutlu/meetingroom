import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from meetingroom.agents import CodexBackend


class CodexStatusTests(unittest.IsolatedAsyncioTestCase):
    async def run_events(self, events):
        statuses = []
        self.activities = []

        async def status(value, activity=None):
            statuses.append(value)
            self.activities.append(activity)

        async def output():
            for event in events:
                yield (json.dumps(event) + '\n').encode()

        proc = SimpleNamespace(
            stdin=SimpleNamespace(write=lambda _: None, drain=AsyncMock(), close=lambda: None),
            stdout=output(), stderr=SimpleNamespace(read=AsyncMock(return_value=b'')),
            wait=AsyncMock(), returncode=0)
        agent = SimpleNamespace(workdir='.', trace=lambda *a, **kw: None, set_status=status)
        backend = object.__new__(CodexBackend)
        backend.agent = agent
        backend.thread_id = 'existing-thread'
        backend._cmd = lambda: ['codex']
        backend._read_limits = AsyncMock()
        with patch('meetingroom.agents.bridge_env', return_value={}), \
                patch('meetingroom.agents.asyncio.create_subprocess_exec', AsyncMock(return_value=proc)):
            self.assertEqual(await backend.turn('test'), 'Done')
        return statuses

    async def test_response_after_command_returns_to_thinking(self):
        statuses = await self.run_events([
            {'type': 'item.started', 'item': {'id': 'a', 'type': 'command_execution', 'command': 'true'}},
            {'type': 'item.completed', 'item': {'id': 'a', 'type': 'command_execution', 'exit_code': 0}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Done'}},
        ])
        self.assertEqual(statuses, ['working', 'thinking', 'thinking'])

    async def test_overlapping_tools_remain_working_until_both_finish(self):
        statuses = await self.run_events([
            {'type': 'item.started', 'item': {'id': 'a', 'type': 'command_execution'}},
            {'type': 'item.started', 'item': {'id': 'b', 'type': 'mcp_tool_call'}},
            {'type': 'item.completed', 'item': {'id': 'a', 'type': 'command_execution'}},
            {'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'Still working'}},
            {'type': 'item.completed', 'item': {'id': 'b', 'type': 'mcp_tool_call'}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Done'}},
        ])
        self.assertEqual(statuses, ['working', 'working', 'thinking', 'thinking'])

    async def test_text_only_response_never_works(self):
        statuses = await self.run_events([
            {'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'Considering'}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Done'}},
        ])
        self.assertNotIn('working', statuses)

    async def test_private_reasoning_is_not_published_as_activity(self):
        await self.run_events([
            {'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'Private deliberation'}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Done'}},
        ])
        self.assertEqual(self.activities, [None, 'Done'])

    async def test_public_progress_and_tool_completion_have_activity(self):
        await self.run_events([
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Checking the input files'}},
            {'type': 'item.started', 'item': {'id': 'a', 'type': 'command_execution', 'command': 'ls'}},
            {'type': 'item.completed', 'item': {'id': 'a', 'type': 'command_execution', 'exit_code': 0}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Done'}},
        ])
        self.assertEqual(self.activities[:3], ['Checking the input files', 'shell: ls', 'Reviewing tool results…'])
