from aletheia.config import Settings
from aletheia.util.installation import install

for path in install(Settings.load()):
    print(path)
