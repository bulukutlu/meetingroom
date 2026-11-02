from pathlib import Path
import tempfile
import unittest
from meetingroom.__main__ import ROOT, DEMO_CFG, load_cfg


class WorkspaceDefaultsTests(unittest.TestCase):
    def config(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'agents.yaml';p.write_text(text)
            return load_cfg(str(p))

    def test_missing_or_relative_workspace_is_repo_relative(self):
        for text in ['agents: []\n', 'agents: []\nworkspace: workspace\n']:
            self.assertEqual(Path(self.config(text)['workspace']),ROOT/'workspace')

    def test_explicit_absolute_workspace_is_preserved(self):
        self.assertEqual(Path(self.config('agents: []\nworkspace: /tmp/custom-meetingroom\n')['workspace']),Path('/tmp/custom-meetingroom'))

    def test_demo_workspace_is_inside_repo(self):
        self.assertEqual(Path(DEMO_CFG['workspace']),ROOT/'workspace/demo')
