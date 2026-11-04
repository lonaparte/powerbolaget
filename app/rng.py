"""Named, independent and serializable random streams.

Each model draws from its own stream (weather knots, faults, society, economy, ...), so adding draws
in one model never shifts another. A stream's full state is saved, so a loaded game continues the same
random sequence.
"""
import hashlib
import random


class Streams:
    def __init__(self, seed, state=None):
        self.seed = int(seed)
        self._streams = {}
        for name, s in (state or {}).items():
            r = random.Random()
            r.setstate((s[0], tuple(s[1]), s[2]))
            self._streams[name] = r

    def __getitem__(self, name):
        r = self._streams.get(name)
        if r is None:
            digest = hashlib.sha256(f'{self.seed}:{name}'.encode()).digest()
            r = self._streams[name] = random.Random(int.from_bytes(digest[:8], 'big'))
        return r

    def state(self):
        out = {}
        for name, r in sorted(self._streams.items()):
            version, internal, gauss_next = r.getstate()
            out[name] = [version, list(internal), gauss_next]
        return out


def stable_unit(*key):
    """A deterministic number in [0, 1) from a key, for fixed per-object traits."""
    digest = hashlib.sha256(':'.join(map(str, key)).encode()).digest()
    return int.from_bytes(digest[:7], 'big')/2**56
