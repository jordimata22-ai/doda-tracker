from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def move_to_trash(path: Path, trash_root: Path) -> Path:
    path = Path(path)
    trash_root = Path(trash_root)
    trash_root.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = trash_root / f"{path.name}__{ts}"

    # Move directory or file safely
    shutil.move(str(path), str(dest))
    return dest
