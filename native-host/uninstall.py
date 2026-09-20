from aletheia.config import Settings
from aletheia.util.installation import uninstall

uninstall(Settings.load())
