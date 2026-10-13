from pathlib import Path
import yaml


def load_settings(path: str | Path = "config/settings.yaml") -> dict:
    with Path(path).open(encoding="utf-8") as file:
        return yaml.safe_load(file)
