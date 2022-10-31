from .settings import *

try:
    from .settings_local import *
except ModuleNotFoundError:
    pass
