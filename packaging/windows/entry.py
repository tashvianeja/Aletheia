import sys

from aletheia.app import main

try:
    raise SystemExit(main())
except Exception:
    if any(
        option in sys.argv
        for option in ("--install-native-host", "--uninstall", "--diagnose", "--smoke-test")
    ):
        # A windowed frozen executable must not leave a hidden traceback dialog
        # blocking its installer. The installer receives a normal failure status.
        raise SystemExit(1) from None
    raise
