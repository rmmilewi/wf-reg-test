import contextlib
import tempfile
from pathlib import Path
from typing import Generator, Iterable, Union, Callable, TypeVar, cast

from gitignore_parser import parse_gitignore  # type: ignore

import xxhash


@contextlib.contextmanager
def create_temp_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def hash_path(path: Union[Path, str, bytes], size: int = 128) -> int:
    hasher = {
        128: xxhash.xxh128(),
        64: xxhash.xxh64(),
        32: xxhash.xxh32(),
    }[size]
    block_size = 1 << 14
    with open(path, "rb") as file:
        while True:
            buffer = file.read(block_size)
            if not buffer:
                break
            hasher.update(buffer)
    return hasher.intdigest()


def hash_bytes(buffer: bytes, size: int = 128) -> int:
    hasher = {
        128: xxhash.xxh128(),
        64: xxhash.xxh64(),
        32: xxhash.xxh32(),
    }[size]
    hasher.update(buffer)
    return hasher.intdigest()


def _ignore_vcs(path: str) -> bool:
    return path == ".git" or path.endswith("/.git")


T = TypeVar("T")
def walk(
        mapper: Callable[[Path, list[T]], T],
        path: Path,
        ignore_preds: tuple[Callable[[str], bool], ...] = (_ignore_vcs,),
) -> T:
    if path.is_dir():
        ignore_file = path / ".gitignore"
        if ignore_file.exists():
            ignore_preds = (
                *ignore_preds,
                cast(Callable[[str], bool], parse_gitignore(ignore_file)),
            )
        children = [
            walk(mapper, subpath, ignore_preds)
            for subpath in path.iterdir()
            if not any(ignore_pred(str(subpath)) for ignore_pred in ignore_preds)
        ]
    else:
        children = []
    return mapper(path, children)