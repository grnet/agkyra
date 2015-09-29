# -*- mode: python -*-
import glob
import os
import sys

def iswin():
    return sys.platform.startswith("win")

def isosx():
    return sys.platform.startswith("darwin")

HERE = os.getcwd()

a = Analysis(['agkyra/scripts/agkyra'],
             pathex=[HERE],
             hiddenimports=[],
             hookspath=None,
             runtime_hooks=None)

def extra_datas(prefix, path):
    def recursive_glob(path, files):
        for file_path in glob.glob(path):
            if os.path.isfile(file_path):
                files.append(os.path.join(prefix, file_path))
            recursive_glob('{}/*'.format(file_path), files)

    files = []
    extra_datas = []

    full_path = os.path.join(prefix, path)
    if os.path.isfile(full_path):
        files.append(full_path)
    else:
        recursive_glob('{}/*'.format(full_path), files)

    for f in files:
        extra_datas.append((f.split(prefix)[1][1:], f, 'DATA'))
    return extra_datas

a.datas += extra_datas(os.path.join(HERE, 'agkyra'), os.path.join('resources', 'nwjs'))
a.datas += extra_datas(os.path.join(HERE, 'agkyra'), os.path.join('resources', 'nwgui'))
a.datas += extra_datas(os.path.join(HERE, 'agkyra'), os.path.join('resources', 'ui_data'))
a.datas += extra_datas(os.path.join(HERE, 'agkyra'), os.path.join('resources', 'cacert.pem'))

pyz = PYZ(a.pure)
exe = EXE(pyz,
          a.scripts,
          exclude_binaries=True,
          name='agkyra.exe' if iswin() else 'agkyra',
          debug=False,
          strip=None,
          upx=True,
          console=True )
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=None,
               upx=True,
               name='agkyra')
if isosx():
    app = BUNDLE(coll,
                 name='agkyra.app',
                 icon=None)
