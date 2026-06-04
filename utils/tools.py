from pathlib import Path


def ensure_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
