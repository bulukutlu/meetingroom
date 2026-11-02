from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from meetingroom.agents import instance_table
from meetingroom.server import Room, create_hub


class RoomSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.catalog=[{'name':'claude','provider':'mock','model':'opus','color':'#d97757'},
                      {'name':'sonnet','provider':'mock','model':'sonnet','color':'#6a8fd8'},
                      {'name':'codex','provider':'mock','color':'#10a37f'}]
        self.app=create_hub({'workspace':self.tmp.name,'agents':self.catalog},8765,'token')
        self.headers={'origin':'http://127.0.0.1:8765'}

    def create(self,names,expected):
        with patch.object(Room,'start'),TestClient(self.app,base_url='http://127.0.0.1:8765') as client:
            response=client.post('/select?t=token',headers=self.headers,json={'agents':names,'location':{'kind':'default'}})
            self.assertEqual(response.status_code,200,response.text)
            room=self.app.state.hub.rooms[response.json()['room']]
            self.assertEqual(list(room.agents),expected)
            self.assertEqual([a['name'] for a in room.snapshot()['agents']],expected)
            listing=client.get('/api/rooms?t=token').json()['rooms']
            self.assertEqual([a['name'] for a in listing[0]['agents']],expected)
            self.assertEqual(len({a.person for a in room.agents.values()}),len(expected))
            return [a.spec for a in room.agents.values()]

    def reject(self,names):
        with patch.object(Room,'start'),TestClient(self.app,base_url='http://127.0.0.1:8765') as client:
            response=client.post('/select?t=token',headers=self.headers,json={'agents':names})
            self.assertEqual(response.status_code,400,response.text)
            self.assertFalse(self.app.state.hub.rooms)

    def test_multiple_instances_of_one_model_keep_selected_handles(self):
        self.create(['sonnet','sonnet-2','sonnet-3'],['sonnet','sonnet-2','sonnet-3'])

    def test_numbered_seats_work_without_the_first_seat(self):
        self.create(['codex-2','codex-4'],['codex-2','codex-4'])

    def test_all_twelve_seats_from_picker_create_twelve_agents(self):
        names=[s['name'] for s in instance_table(self.catalog)]
        specs=self.create(names,names)
        for model in self.catalog:
            self.assertEqual({s['color'] for s in specs if s['name']==model['name'] or s['name'].startswith(model['name']+'-')},{model['color']})

    def test_legacy_repeated_base_names_still_expand(self):
        self.create(['sonnet','sonnet'],['sonnet','sonnet-2'])

    def test_unknown_seat_is_rejected_instead_of_silently_dropped(self):
        self.reject(['claude','sonnet-9'])

    def test_more_than_four_copies_of_one_type_is_rejected(self):
        self.reject(['sonnet']*5)

    def test_more_than_twelve_seats_is_rejected(self):
        names=[s['name'] for s in instance_table(self.catalog)]
        self.reject(names+['claude'])

    def test_malformed_and_empty_selections_are_rejected(self):
        for names in [[],None,'sonnet',[{}],[12]]:
            with self.subTest(names=names):self.reject(names)
