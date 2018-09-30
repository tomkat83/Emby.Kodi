try:
    from .signal import Signal
    from .slot import Slot
    from .exceptions import *
except ImportError:  # pragma: no cover
    # Possible we are running from setup.py, in which case we're after
    # the __version__ string only.
    pass

__version__ = '0.1.1'
