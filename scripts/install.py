from __future__ import annotations

import argparse

from aletheia.config import Settings
from aletheia.util.installation import install, uninstall

parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["install", "uninstall"])
args = parser.parse_args()
if args.action == "install":
    for path in install(Settings.load()):
        print(path)
else:
    uninstall(Settings.load())
