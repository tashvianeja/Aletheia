from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

root = Path(SPECPATH).parents[1]
datas = collect_data_files('privacy_guardian') + collect_data_files('en_core_web_sm')
datas += collect_data_files('onnxruntime')
datas += [(str(root/'extension'),'extension')]
if (root/'build/tesseract').exists():
    datas += [(str(root/'build/tesseract'),'tesseract')]
hiddenimports = collect_submodules('privacy_guardian') + collect_submodules('en_core_web_sm')
hiddenimports += collect_submodules('onnxruntime') + collect_submodules('pyap')
a = Analysis([str(root/'packaging/entry.py')], pathex=[str(root/'src')], binaries=collect_dynamic_libs('onnxruntime'), datas=datas, hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[str(root/'packaging/runtime.py')], excludes=['tkinter','matplotlib','scipy','IPython','pytest'])
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='PrivacyGuardian',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False)
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PrivacyGuardian')
app = BUNDLE(coll,name='PrivacyGuardian.app',bundle_identifier='com.privacyguardian.app',info_plist={'LSUIElement':True,'LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True,'NSAppleEventsUsageDescription':'Open system privacy settings when requested.'})
