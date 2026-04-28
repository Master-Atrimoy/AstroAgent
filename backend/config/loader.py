"""Thread-safe Hydra config loader using Compose API (not @hydra.main)."""
from __future__ import annotations
import threading
from pathlib import Path
from omegaconf import DictConfig, OmegaConf
from hydra import compose, initialize_config_dir
from hydra.core.global_hydra import GlobalHydra

_lock = threading.Lock()
_cfg: DictConfig | None = None


def get_config(overrides: list[str] | None = None) -> DictConfig:
    global _cfg
    with _lock:
        if _cfg is None or overrides:
            GlobalHydra.instance().clear()
            conf_dir = str(Path(__file__).parents[2] / "conf")
            with initialize_config_dir(config_dir=conf_dir, version_base="1.3"):
                _cfg = compose(config_name="config", overrides=overrides or [])
    return _cfg
