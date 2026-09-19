from __future__ import annotations

import argparse

from privacy_guardian.config import Settings
from privacy_guardian.util.installation import install, uninstall

parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["install", "uninstall"])
args = parser.parse_args()
if args.action == "install":
    for path in install(Settings.load()):
        print(path)
else:
    uninstall(Settings.load())
