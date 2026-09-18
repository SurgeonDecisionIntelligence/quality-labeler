"""Load series in background threads so moving to the next one is instant."""

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from .dicom_io import Series, load_series


class Prefetcher:
    def __init__(self, paths: list[Path], root: Path, ahead: int = 3, behind: int = 2):
        self.paths, self.root = paths, root
        self.ahead, self.behind = ahead, behind
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._cache: dict[int, Future[Series]] = {}

    def get(self, index: int) -> Future[Series]:
        if index not in self._cache:
            self._cache[index] = self._pool.submit(load_series, self.paths[index], self.root)
        return self._cache[index]

    def prime(self, index: int, upcoming: list[int]):
        """Keep `index` and the next few `upcoming` indices loaded; evict the rest."""
        keep = {index, *upcoming[: self.ahead]}
        keep |= set(range(max(0, index - self.behind), index))
        for i in list(self._cache):
            if i not in keep:
                self._cache.pop(i).cancel()
        self.get(index)
        for i in upcoming[: self.ahead]:
            self.get(i)

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)
