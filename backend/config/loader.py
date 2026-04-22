"""Hydra Compose API loader — thread-safe, absolute path, cached."""
from __future__ import annotations
import threading
from pathlib import Path

_CONFIG_DIR = str((Path(__file__).parents[2] / "conf").resolve())
_cache = None
_lock  = threading.Lock()


def load_config(overrides: list[str] | None = None):
    global _cache
    if _cache is not None and not overrides:
        return _cache
    with _lock:
        if _cache is not None and not overrides:
            return _cache
        from hydra import compose, initialize_config_dir
        from hydra.core.global_hydra import GlobalHydra
        GlobalHydra.instance().clear()
        with initialize_config_dir(config_dir=_CONFIG_DIR, version_base="1.3"):
            cfg = compose(config_name="config", overrides=overrides or [])
        if not overrides:
            _cache = cfg
        return cfg
