from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parents[1]
datas = collect_data_files('privacy_guardian') + collect_data_files('en_core_web_sm') + [(str(root/'extension'),'extension')]
if (root/'build/tesseract').exists():
    datas += [(str(root/'build/tesseract'),'tesseract')]
hiddenimports = collect_submodules('privacy_guardian') + collect_submodules('en_core_web_sm') + ['win32timezone','win32com.client']
a = Analysis([str(root/'packaging/entry.py')],pathex=[str(root/'src')],datas=datas,hiddenimports=hiddenimports,runtime_hooks=[str(root/'packaging/runtime.py')],excludes=['tkinter','matplotlib','scipy','IPython','pytest'])
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='PrivacyGuardian',console=False,upx=False)
host = Analysis([str(root/'native-host/host.py')],pathex=[str(root/'src')],hiddenimports=['privacy_guardian.core.ipc.native_host'],excludes=['PySide6','spacy','numpy'])
host_pyz = PYZ(host.pure)
host_exe = EXE(host_pyz,host.scripts,[],exclude_binaries=True,name='PrivacyGuardianHost',console=True,upx=False)
coll = COLLECT(exe,host_exe,a.binaries,a.datas,host.binaries,host.datas,name='PrivacyGuardian',upx=False)
