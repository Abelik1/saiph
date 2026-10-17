# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build the bundled Saiph camera filters from pinned corresponding source."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
HASHES = {
    'shared.inl': '3068dd94ac0d70f163120fff93996d80cb0d30c0c33fd427e32e8ae4ec964dd0',
    'streams.cpp': 'f6a05eb379a636343a28cbf6177f8c175e86da9f49fc946a8deb942b193ed0e6',
    'streams.h': 'd9b949e04c4bf4c65f619dc5da95380ba7a3289a5427d5ade5d9b64037a83e6d',
    'UnityCaptureFilter.cpp': 'd1665506a9566ee11c3492c07865f5a6db38b298ed893da4d5e31791ee2f65f4',
    'UnityCaptureFilter.def': 'e9f66b03e84671fc0bbeb8250278a037d935fa1eedd264670059b1691b873ec9',
}


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Pinned camera source patch no longer matches.')
    return text.replace(old, new)


def generate(output):
    output.mkdir(parents=True, exist_ok=True)
    sources = {}
    for name, expected in HASHES.items():
        raw = (HERE / 'upstream' / name).read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Pinned upstream camera source differs: ' + name)
        sources[name] = raw.decode('utf-8')
    shared = sources['shared.inl']
    shared = replace(shared, '(3840 * 2160 * 4 * sizeof(short))', '(1280 * 720 * 4)')
    shared = replace(shared, "('z' - '0')", '0')
    shared = shared.replace('UnityCapture_', 'OrionSaiphCameraV1_')
    shared = replace(shared, 'OpenMutexA(SYNCHRONIZE,', 'OpenMutexA(SYNCHRONIZE | MUTEX_MODIFY_STATE,')
    shared = replace(shared, 'WaitForSingleObject(m_hMutex, INFINITE); //lock mutex\n\t\tcallback',
        '''if (WaitForSingleObject(m_hMutex, 1000) != WAIT_OBJECT_0) return RECEIVERES_CAPTUREINACTIVE;
        if (m_pSharedBuf->width != 1280 || m_pSharedBuf->height != 720 || m_pSharedBuf->stride != 1280
            || m_pSharedBuf->format != FORMAT_UINT8 || m_pSharedBuf->maxSize != MAX_SHARED_IMAGE_SIZE) {
            ReleaseMutex(m_hMutex); return RECEIVERES_CAPTUREINACTIVE;
        }
        callback''')
    shared = replace(shared, 'if (m_pSharedBuf->maxSize < DataSize) return SENDRES_TOOLARGE;',
        'if (DataSize != MAX_SHARED_IMAGE_SIZE || m_pSharedBuf->maxSize != MAX_SHARED_IMAGE_SIZE) return SENDRES_TOOLARGE;')
    shared = replace(shared, 'WaitForSingleObject(m_hMutex, INFINITE); //lock mutex\n\t\tm_pSharedBuf->width',
        'if (WaitForSingleObject(m_hMutex, 1000) != WAIT_OBJECT_0) return SENDRES_TOOLARGE;\n\t\tm_pSharedBuf->width')
    shared = replace(shared, 'WaitForSingleObject(m_hMutex, INFINITE); //lock mutex\n\t\tstruct UnlockAtReturn',
        'if (WaitForSingleObject(m_hMutex, 1000) != WAIT_OBJECT_0) return false;\n\t\tstruct UnlockAtReturn')
    source = sources['UnityCaptureFilter.cpp']
    source = replace(source, '#define CaptureSourceName L"Unity Video Capture"', '#define CaptureSourceName L"Saiph Camera"')
    for old, new in [('0x10', '0x40'), ('0x11', '0x41'), ('0x20', '0x42'), ('0x21', '0x43')]:
        source = replace(source, '0x5c2cd55c, 0x92ad, 0x4999, 0x86, 0x66, 0x91, 0x2b, 0xd3, 0xe7, 0x00, ' + old,
            '0xd9b25791, 0x5540, 0x48be, 0x84, 0x2c, 0xc7, 0x3b, 0xf8, 0x54, 0x03, ' + new)
    start = source.index('static struct { int width, height; } _media[] =')
    end = source.index('//Error draw modes', start)
    source = source[:start] + 'static struct { int width, height; } _media[] = {{1280,720},{640,360},{0,0}};\n\n' + source[end:]
    source = replace(source, '{ EDM_BLUEPINK, EDM_GREENYELLOW, EDM_GREENKEY }', '{ EDM_BLACK, EDM_BLACK, EDM_BLACK }')
    # Registration is Saiph-owned and per-user; none of the upstream machine-wide
    # registration, multiple-device or command-line custom-name paths are built.
    start = source.index('static HRESULT RegisterFilters(BOOL bRegister)')
    end = source.index('extern "C" BOOL WINAPI DllEntryPoint', start)
    source = source[:start] + source[end:]
    (output / 'shared.inl').write_text(shared, encoding='utf-8')
    (output / 'UnityCaptureFilter.cpp').write_text(source, encoding='utf-8')
    for name in ('streams.cpp', 'streams.h'):
        (output / name).write_text(sources[name], encoding='utf-8')
    (output / 'SaiphCamera.def').write_text('EXPORTS\n DllRegisterServer PRIVATE\n DllUnregisterServer PRIVATE\n DllGetClassObject PRIVATE\n DllCanUnloadNow PRIVATE\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Windows C++ tools are required to build the Windows camera component.')
    output = args.output.resolve()
    generated = output / 'generated'
    generate(generated)
    for arch, generator in [('64', 'x64'), ('32', 'Win32')]:
        build = output / ('cmake-' + arch)
        subprocess.run(['cmake', '-S', str(HERE), '-B', str(build), '-A', generator,
                        '-DGENERATED=' + str(generated)], check=True)
        subprocess.run(['cmake', '--build', str(build), '--config', 'Release', '--parallel', '2'], check=True)
        shutil.copyfile(build / 'Release/SaiphCamera.dll', output / ('SaiphCamera' + arch + '.dll'))
    shutil.copyfile(HERE / 'LICENSE.UnityCapture.txt', output / 'LICENSE.UnityCapture.txt')
    receipt = {'schema': 1, 'format': 'saiph-camera-build', 'upstreamCommit': '3ed54c325e0ad71afcf4f246c07e5e17b3d7f2d2',
               'sourceFiles': {str(f.relative_to(HERE)): hashlib.sha256(f.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                               for f in HERE.rglob('*') if f.is_file() and f.suffix != '.pyc' and '__pycache__' not in f.parts},
               'files': {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                         for name in ('SaiphCamera64.dll', 'SaiphCamera32.dll', 'LICENSE.UnityCapture.txt')}}
    (output / 'camera-build.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print('Built both Saiph Camera components. No camera was installed or registered.')


if __name__ == '__main__':
    main()
