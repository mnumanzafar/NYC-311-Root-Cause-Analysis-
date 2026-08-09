"""Execute sql/ layers in dependency order: staging -> intermediate -> marts.

Within a layer, files run alphabetically unless the layer has an ``order.txt``
listing filenames; those run first, in the listed order, then the remainder
alphabetically. This keeps mart-on-mart dependencies explicit.
"""
from __future__ import annotations

import logging

from ..utils.config_loader import ROOT, setup_logging
from ..utils.db import execute_script

log = logging.getLogger(__name__)
LAYERS = ("staging", "intermediate", "marts")


def layer_files(layer: str) -> list:
    directory = ROOT / "sql" / layer
    files = sorted(directory.glob("*.sql"))
    order_file = directory / "order.txt"
    if not order_file.exists():
        return files
    priority = [
        line.strip()
        for line in order_file.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    ranked = [directory / name for name in priority if (directory / name).exists()]
    return ranked + [f for f in files if f not in ranked]


def run() -> list[str]:
    executed = []
    for layer in LAYERS:
        for path in layer_files(layer):
            log.info("running %s/%s", layer, path.name)
            execute_script(path.read_text())
            executed.append(f"{layer}/{path.name}")
    return executed


if __name__ == "__main__":
    setup_logging()
    run()
