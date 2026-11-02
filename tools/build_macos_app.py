#!/usr/bin/env python3
"""Build a small native Dock launcher; reuse the project, environment and models."""
from __future__ import annotations
import argparse
import json
import os
import platform
import re
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / 'meetingroom/__init__.py').read_text()).group(1)


def build(output: Path, project: Path = ROOT, replace: bool = False):
    if output.exists():
        if not replace:
            raise SystemExit(f'{output} already exists; use --replace to rebuild the generated launcher.')
        info = plistlib.loads((output / 'Contents/Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != 'local.berkin.meetingroom':
            raise SystemExit('Refusing to replace a different application.')
    with tempfile.TemporaryDirectory(prefix='meetingroom-app-') as temporary:
        temp = Path(temporary)
        bundle = temp / 'Meeting Room.app'
        contents = bundle / 'Contents'
        executable = contents / 'MacOS/MeetingRoom'
        resources = contents / 'Resources'
        executable.parent.mkdir(parents=True)
        resources.mkdir()
        env = dict(os.environ, CLANG_MODULE_CACHE_PATH=str(temp / 'modules'))
        sdk = subprocess.check_output(['/usr/bin/xcrun', '--show-sdk-path'], text=True).strip()
        clang_headers = subprocess.check_output(['/usr/bin/xcrun', 'clang', '-print-resource-dir'], text=True).strip() + '/include'
        subprocess.run(['/usr/bin/swiftc', '-swift-version', '5', '-O', '-sdk', sdk,
                        '-target', f'{platform.machine()}-apple-macos13.0',
                        '-Xcc', '-Xclang', '-Xcc', '-nostdsysteminc',
                        '-Xcc', '-isystem', '-Xcc', clang_headers,
                        '-Xcc', '-isystem', '-Xcc', str(Path(sdk) / 'usr/include'),
                        '-module-cache-path', str(temp / 'modules'),
                        '-framework', 'AppKit', str(ROOT / 'tools/macos/MeetingRoom.swift'), '-o', str(executable)],
                       env=env, check=True)
        executable.chmod(0o755)
        (resources / 'project.json').write_text(json.dumps({'directory': str(project.resolve())}))
        # Render the existing SVG's rectangle primitives; keep the established door icon.
        from PIL import Image, ImageDraw
        icon = Image.new('RGBA', (1024, 1024))
        draw = ImageDraw.Draw(icon)
        draw.rounded_rectangle((25,25,999,999),radius=210,fill='#1b1510')
        svg = ET.fromstring((ROOT / 'meetingroom/static/favicon.svg').read_text())
        scale = 28
        for rect in svg:
            if not rect.tag.endswith('rect'): continue
            x = 148 + (float(rect.attrib['x']) - 3) * scale
            y = 148 + (float(rect.attrib['y']) - 3) * scale
            w = float(rect.attrib['width']) * scale
            h = float(rect.attrib['height']) * scale
            draw.rectangle((round(x),round(y),round(x+w-1),round(y+h-1)),fill=rect.attrib['fill'])
        icon.save(resources / 'MeetingRoom.icns', format='ICNS')
        info = {'CFBundleIdentifier':'local.berkin.meetingroom','CFBundleName':'Meeting Room',
                'CFBundleDisplayName':'Meeting Room','CFBundleExecutable':'MeetingRoom',
                'CFBundlePackageType':'APPL','CFBundleVersion':VERSION,'CFBundleShortVersionString':VERSION,
                'CFBundleIconFile':'MeetingRoom.icns','NSPrincipalClass':'NSApplication',
                'LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True}
        (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
        subprocess.run(['/usr/bin/codesign','--force','--sign','-','--timestamp=none',str(bundle)],check=True)
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(bundle)],check=True)
        subprocess.run([str(executable), '--self-test'], check=True)
        output.parent.mkdir(parents=True,exist_ok=True)
        if output.exists(): shutil.rmtree(output)
        shutil.copytree(bundle,output)
        icon.resize((512,512),Image.Resampling.NEAREST).save(ROOT / 'docs/macos-launcher-icon.png')
    print(f'Built: {output}')
    print('Double-click to launch. Drag the app to the Dock to keep it there.')
    print('The project folder must stay in place; this launcher reuses its environment and models.')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT / 'Meeting Room.app')
    p.add_argument('--replace',action='store_true')
    a=p.parse_args()
    build(a.output.resolve(),replace=a.replace)
