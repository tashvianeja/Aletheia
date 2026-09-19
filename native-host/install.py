from privacy_guardian.config import Settings
from privacy_guardian.util.installation import install

for path in install(Settings.load()):
    print(path)
