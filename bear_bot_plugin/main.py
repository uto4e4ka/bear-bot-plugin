import asyncio

from potehinsonnet.monitoring.health import Health
from potehinsonnet.net import NatsClient
from bear_bot_plugin import config
from bear_bot_plugin.core import Core
from dotenv import load_dotenv
from potehinsonnet.steup.install import Install
from potehinsonnet.net_models.discord_models import Command,CommandRegister
import os

load_dotenv()
channel_id = os.getenv('CHANNEL_ID')

async def main():
    client = NatsClient()
    await client.connect()
    Health(client,config.PLUGIN_NAME)
    core = Core(client,channel_id)
    await core.start()
    install = Install(client,config.PLUGIN_NAME,"")
    await install.register_commands(CommandRegister(command=[Command(name="beer",description="Узнать цену на пиво",service=config.PLUGIN_NAME,tag="beer")]))
    await asyncio.Event().wait()

asyncio.run(main())