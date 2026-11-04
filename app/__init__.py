"""Powerbolaget: an open island energy, economy and society simulation (Linux runtime)."""
import sys

__version__ = '0.1.0'

if sys.platform != 'linux':
    raise RuntimeError(
        'Powerbolaget requires Linux. Use Docker Compose with Linux containers '
        'on other operating systems.'
    )
