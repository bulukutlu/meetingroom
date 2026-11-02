"""Read-only desktop graphics hints. Browser WebGL 2 is checked by the page itself."""
from __future__ import annotations
import ctypes.util
import os
import platform
import shutil


def graphics_diagnostics() -> list[str]:
    lines = ['3D requires WebGL 2 in your browser. The page tests it before opening the 3D view.']
    if platform.system() != 'Linux':
        return lines
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        lines.append('No desktop display detected here. If using SSH/remote desktop, check graphics in the desktop/browser session you actually use.')
    missing = [name for name in ('EGL', 'GL') if not ctypes.util.find_library(name)]
    if missing:
        lines.append('System graphics libraries not found: ' + ', '.join(missing) + '. Browser-bundled libraries may differ.')
        lines.append('On Ubuntu with Intel/AMD Mesa graphics: sudo apt install libgl1 libegl1 libgl1-mesa-dri libegl-mesa0 mesa-utils')
    if shutil.which('glxinfo'):
        lines.append('For desktop driver details: glxinfo -B (this does not test browser WebGL 2).')
    else:
        lines.append('Optional Ubuntu driver diagnostics: sudo apt install mesa-utils; then run glxinfo -B.')
    lines.append('For NVIDIA on Ubuntu: Software & Updates > Additional Drivers, choose the recommended tested driver, then reboot.')
    lines.append('In Chrome/Edge, enable graphics acceleration and relaunch; inspect chrome://gpu or edge://gpu for WebGL2 problems.')
    return lines


def startup_graphics_notice():
    for line in graphics_diagnostics():
        print('  graphics: ' + line, flush=True)


if __name__ == '__main__':
    startup_graphics_notice()
