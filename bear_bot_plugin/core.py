from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from potehinsonnet.discord_provider import DiscordProvider
from potehinsonnet.net_models.discord_models import NatsMessage

from bear_bot_plugin import beer_utils
from bear_bot_plugin.config import PLUGIN_NAME, BeerSettings

TIMEZONE = ZoneInfo("Europe/Samara")
DAILY_JOB = "daily_price"


class BeerService:
    """Цена пива и ежедневная рассылка. Запускается вместе с плагином (lifespan)."""

    def __init__(self, discord: DiscordProvider, settings: BeerSettings):
        self.discord = discord
        self.settings = settings
        self.scheduler = AsyncIOScheduler(timezone=TIMEZONE)
        self.price: float | None = None
        self.prev_price: float | None = beer_utils.read_prev_price()
        self.checked_at: datetime | None = None

    async def __aenter__(self):
        self._schedule()
        self.scheduler.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.scheduler.shutdown(wait=False)

    def _schedule(self) -> None:
        if self.scheduler.get_job(DAILY_JOB):
            self.scheduler.remove_job(DAILY_JOB)
        if self.settings.daily and self.settings.channel_id:
            self.scheduler.add_job(
                self.send_to_channel, "cron", id=DAILY_JOB,
                hour=self.settings.hour, minute=self.settings.minute,
            )

    @property
    def next_run(self) -> datetime | None:
        job = self.scheduler.get_job(DAILY_JOB)
        return job.next_run_time if job else None

    async def refresh_price(self) -> str:
        """Проверяет цену и возвращает сообщение со стрелкой относительно прошлой проверки."""
        current = await beer_utils.fetch_beer_price()
        if current is None:
            return beer_utils.format_price_message(None, None)

        prev = beer_utils.read_prev_price()
        beer_utils.write_prev_price(current)
        self.price, self.prev_price, self.checked_at = current, prev, datetime.now(TIMEZONE)
        return beer_utils.format_price_message(current, prev)

    async def send_to_channel(self) -> None:
        if not self.settings.channel_id:
            raise ValueError("Канал для рассылки не задан")
        await self.discord.send_message(NatsMessage(
            service=PLUGIN_NAME,
            text=await self.refresh_price(),
            channel_id=self.settings.channel_id,
        ))

    def update_settings(self, channel_id: int | None, daily: bool, hour: int, minute: int) -> None:
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("Время: часы от 0 до 23, минуты от 0 до 59")
        if daily and not channel_id:
            raise ValueError("Для ежедневной рассылки укажите канал")
        self.settings = BeerSettings(channel_id=channel_id, daily=daily, hour=hour, minute=minute)
        self.settings.save()
        self._schedule()
