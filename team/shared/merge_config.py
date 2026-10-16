#!/usr/bin/env python3
"""merge_config.py <config.yaml> <overlay.yaml> — deep-merge overlay into a Hermes config.

Mappings merge recursively; lists are unioned (existing order kept, new items appended);
scalars from the overlay win. The original is saved once as config.yaml.pre-research-team.
"""
import shutil
import sys
from pathlib import Path

import yaml


def merge(base, over):
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = merge(base.get(k), v) if k in base else v
        return out
    if isinstance(base, list) and isinstance(over, list):
        return base + [x for x in over if x not in base]
    return over


cfg, overlay = Path(sys.argv[1]), Path(sys.argv[2])
base = yaml.safe_load(cfg.read_text()) if cfg.exists() else {}
backup = cfg.with_name(cfg.name + ".pre-research-team")
if cfg.exists() and not backup.exists():
    shutil.copy2(cfg, backup)
merged = merge(base or {}, yaml.safe_load(overlay.read_text()) or {})
cfg.write_text(yaml.safe_dump(merged, sort_keys=False, allow_unicode=True))
print(f"merged {overlay.name} -> {cfg}")
