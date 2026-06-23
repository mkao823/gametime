from __future__ import annotations

import csv
import tarfile
from io import BytesIO, TextIOWrapper
from itertools import product
from pathlib import Path
from typing import Optional, Sequence, Union
from urllib.request import urlopen

import pandas as pd

LIST_URL = "https://raw.githubusercontent.com/shufinskiy/nba_data/main/list_data.txt"


def load_nba_data(
    path: Union[Path, str] = Path.cwd(),
    seasons: Union[Sequence[int], int] = range(2021, 2024),
    data: Union[Sequence[str], str] = ("nbastats",),
    seasontype: str = "rg",
    league: str = "nba",
    untar: bool = True,
    in_memory: bool = False,
    use_pandas: bool = True,
) -> Optional[pd.DataFrame]:
    if isinstance(path, str):
        path = Path(path).expanduser()
    if isinstance(seasons, int):
        seasons = (seasons,)
    if isinstance(data, str):
        data = (data,)

    if len(data) > 1 and in_memory:
        raise ValueError("in_memory=True only supports a single data type")

    if seasontype == "rg":
        need_data = tuple(f"{d}_{s}" for d, s in product(data, seasons))
    elif seasontype == "po":
        need_data = tuple(f"{d}_po_{s}" for d, s in product(data, seasons))
    elif seasontype == "both":
        need_rg = tuple(f"{d}_{s}" for d, s in product(data, seasons))
        need_po = tuple(f"{d}_po_{s}" for d, s in product(data, seasons))
        need_data = need_rg + need_po
    else:
        raise ValueError(f"Unknown seasontype: {seasontype}")

    path.mkdir(parents=True, exist_ok=True)
    with urlopen(LIST_URL) as resp:
        lines = resp.read().decode("utf-8").strip().split("\n")
    name_to_url = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in lines}
    need_name = [n for n in name_to_url if n in need_data]
    if not need_name:
        raise ValueError(f"No archives for {need_data}")

    table = pd.DataFrame() if (in_memory and use_pandas) else None
    for name in need_name:
        with urlopen(name_to_url[name]) as response:
            content = response.read()
        if in_memory:
            with tarfile.open(fileobj=BytesIO(content), mode="r:xz") as tar:
                member = tar.extractfile(f"{name}.csv")
                chunk = pd.read_csv(member)
                table = pd.concat([table, chunk], ignore_index=True)
        else:
            archive_path = path / f"{name}.tar.xz"
            archive_path.write_bytes(content)
            if untar:
                with tarfile.open(archive_path) as tar:
                    tar.extract(f"{name}.csv", path=path)
                archive_path.unlink(missing_ok=True)
    return table if in_memory else None
