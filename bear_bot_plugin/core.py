from zoneinfo import ZoneInfo

from potehinsonnet.net import NatsClient
from bear_bot_plugin import beer_utils,config
from potehinsonnet.net_models.discord_models import NatsMessage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

class Core:
    def __init__(self,client: NatsClient,channel_id: int):
        self.scheduler = AsyncIOScheduler(timezone=ZoneInfo("Europe/Samara"))
        self.client = client
        self.group_id = channel_id


    async def daily_message(self):
        await self.send_message()

    async def send_message(self, ignored=None):
        if ignored is None:
            ignored = {}
        await self.client.publish("discord.message.send", NatsMessage(
            service=config.PLUGIN_NAME,
            text=beer_utils.build_price_message(),
            channel_id=self.group_id,
        ).model_dump(mode="json"))

    async def start(self):
        self.scheduler.add_job(
            self.daily_message,
            "cron",
            hour=10,
            minute=0,
            second=0,
        )
        self.scheduler.start()
        await self.client.subscribe("discord.command.execute",self.send_message)

