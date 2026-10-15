"""Настройки рассылки: меняются из веб-панели и переживают перезапуск."""
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

PLUGIN_NAME = "bear_bot_plugin"   # то же имя, что в plugin.toml
PACKAGE_DIR = Path(__file__).parent
DATA_DIR = PACKAGE_DIR / "data"     # меняет create_plugin: туда, куда скажет хост (PluginContext.data_dir)
LEGACY_FILES = {"settings.json": "beer_settings.json", "events.json": "events.json",
                "prev_price.txt": "prev_price.txt"}   # раньше лежали прямо в пакете


def use_data_dir(path: Path) -> None:
    """Где хранить данные. Старые файлы из пакета переезжают туда один раз."""
    global DATA_DIR
    DATA_DIR = Path(path)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for old_name, new_name in LEGACY_FILES.items():
        old, new = PACKAGE_DIR / old_name, DATA_DIR / new_name
        if old.exists() and not new.exists():
            old.replace(new)


def data_file(name: str) -> Path:
    return DATA_DIR / name


@dataclass
class BeerSettings:
    channel_id: int | None = None
    daily: bool = True
    hour: int = 10
    minute: int = 0

    @classmethod
    def load(cls) -> "BeerSettings":
        path = data_file("beer_settings.json")
        if path.exists():
            try:
                return cls(**json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, TypeError):
                pass
        # Первый запуск: канал из .env, как было раньше
        channel = os.getenv("CHANNEL_ID")
        return cls(channel_id=int(channel) if channel and channel.isdigit() else None)

    def save(self) -> None:
        data_file("beer_settings.json").write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
