"""Powerbolaget's supported Linux runtime."""
import sys

if sys.platform != 'linux':
    raise RuntimeError(
        'Powerbolaget requires Linux. Use Docker Compose with Linux containers '
        'on other operating systems.'
    )
