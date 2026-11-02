import unittest
from unittest.mock import patch
from meetingroom.graphics import graphics_diagnostics


class GraphicsDiagnosticsTests(unittest.TestCase):
    def test_linux_missing_libraries_and_display_get_actionable_advisory(self):
        with patch('meetingroom.graphics.platform.system',return_value='Linux'), \
             patch.dict('os.environ',{},clear=True), \
             patch('meetingroom.graphics.ctypes.util.find_library',return_value=None), \
             patch('meetingroom.graphics.shutil.which',return_value=None):
            text='\n'.join(graphics_diagnostics())
        self.assertIn('No desktop display',text)
        self.assertIn('EGL, GL',text)
        self.assertIn('libgl1-mesa-dri',text)
        self.assertIn('Additional Drivers',text)
        self.assertNotIn('passed',text.lower())

    def test_present_libraries_do_not_claim_browser_webgl_support(self):
        with patch('meetingroom.graphics.platform.system',return_value='Linux'), \
             patch.dict('os.environ',{'DISPLAY':':0'},clear=True), \
             patch('meetingroom.graphics.ctypes.util.find_library',return_value='available'), \
             patch('meetingroom.graphics.shutil.which',return_value='/usr/bin/glxinfo'):
            text='\n'.join(graphics_diagnostics())
        self.assertNotIn('No desktop display',text)
        self.assertNotIn('not found',text)
        self.assertIn('does not test browser',text)

    def test_mac_has_browser_check_without_ubuntu_package_instructions(self):
        with patch('meetingroom.graphics.platform.system',return_value='Darwin'):
            text='\n'.join(graphics_diagnostics())
        self.assertIn('WebGL 2',text)
        self.assertNotIn('apt install',text)
