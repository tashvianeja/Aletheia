from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parents[1]
datas = collect_data_files('aletheia') + collect_data_files('en_core_web_sm')
datas += collect_data_files('onnxruntime') + [(str(root/'extension'),'extension')]
if (root/'build/tesseract').exists():
    datas += [(str(root/'build/tesseract'),'tesseract')]
native_imports = ['win32security', 'win32api', 'ntsecuritycon', 'winreg', 'pythoncom', 'pywintypes', 'win32timezone', 'win32com.client']
hiddenimports = collect_submodules('aletheia') + collect_submodules('en_core_web_sm')
hiddenimports += collect_submodules('onnxruntime') + collect_submodules('pyap') + native_imports
# The Gemini SDK is a namespace package that reaches google.auth dynamically, so static
# analysis alone leaves the optional cloud path missing at runtime. Its bundled tests and
# its agent/interaction layer are 520 modules this app never calls.
genai_used = lambda name: not name.startswith(('google.genai.tests', 'google.genai._gaos'))
hiddenimports += collect_submodules('google.genai', filter=genai_used)
hiddenimports += collect_submodules('google.auth')
a = Analysis([str(root/'packaging/windows/entry.py')],pathex=[str(root/'src')],datas=datas,hiddenimports=hiddenimports,runtime_hooks=[str(root/'packaging/runtime.py')],excludes=['tkinter','matplotlib','scipy','IPython','pytest'])
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='Aletheia',console=False,upx=False)
host = Analysis([str(root/'native-host/host.py')],pathex=[str(root/'src')],hiddenimports=['aletheia.core.ipc.native_host'] + native_imports,excludes=['PySide6','spacy','numpy'])
host_pyz = PYZ(host.pure)
host_exe = EXE(host_pyz,host.scripts,[],exclude_binaries=True,name='AletheiaHost',console=True,upx=False)
coll = COLLECT(exe,host_exe,a.binaries,a.datas,host.binaries,host.datas,name='Aletheia',upx=False)
