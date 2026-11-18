"""A research file that is kept gzipped on disk.

The two market histories are ~220 MB of JSON as plain text and about a fifth of
that compressed. `BigJson(path)` is a path that reads `<path>.gz` when it is
there and the plain file when it is not, and always writes the compressed one,
so the modules that say `DATA.read_text()` did not have to change.
"""

from __future__ import annotations

import gzip
import pathlib


class BigJson(type(pathlib.Path())):
    def _gz(self) -> pathlib.Path:
        return pathlib.Path(str(self) + ".gz")

    def exists(self) -> bool:
        return self._gz().exists() or pathlib.Path(str(self)).exists()

    def read_text(self, encoding="utf-8", errors=None) -> str:
        packed = self._gz()
        if packed.exists():
            with gzip.open(packed, "rt", encoding=encoding, errors=errors) as handle:
                return handle.read()
        return pathlib.Path(str(self)).read_text(encoding=encoding, errors=errors)

    def write_text(self, data, encoding="utf-8", errors=None) -> int:
        with gzip.open(self._gz(), "wt", encoding=encoding, errors=errors) as handle:
            return handle.write(data)
