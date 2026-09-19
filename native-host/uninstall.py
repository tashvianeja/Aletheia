from privacy_guardian.config import Settings
from privacy_guardian.util.installation import uninstall

uninstall(Settings.load())
