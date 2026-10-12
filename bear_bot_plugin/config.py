"""Настройки рассылки: меняются из веб-панели и переживают перезапуск."""
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

PLUGIN_NAME = "bear_bot_plugin"
SETTINGS_FILE = Path(__file__).parent / "settings.json"


@dataclass
class BeerSettings:
    channel_id: int | None = None
    daily: bool = True
    hour: int = 10
    minute: int = 0

    @classmethod
    def load(cls) -> "BeerSettings":
        if SETTINGS_FILE.exists():
            try:
                return cls(**json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
            except (ValueError, TypeError):
                pass
        # Первый запуск: канал из .env, как было раньше
        channel = os.getenv("CHANNEL_ID")
        return cls(channel_id=int(channel) if channel and channel.isdigit() else None)

    def save(self) -> None:
        SETTINGS_FILE.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
