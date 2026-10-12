import os

from dotenv import load_dotenv
from potehinsonnet import Plugin
from potehinsonnet.net_models.discord_models import Command, ExecutedCommand, ExecutedCommandResponse
from potehinsonnet.net_models.panel_ui import (
    Button,
    ChannelPicker,
    Form,
    KeyValue,
    Link,
    NumberField,
    PanelContext,
    PanelPage,
    Text,
    Toggle,
)
from potehinsonnet.net_models.system_models import Service

from bear_bot_plugin import beer_utils
from bear_bot_plugin.config import PLUGIN_NAME, BeerSettings
from bear_bot_plugin.core import BeerService

SERVICE = Service(
    name=PLUGIN_NAME,
    label="🍺 Пивная биржа",
    description="Цена пива и ежедневная рассылка",
    author="Uto4ka404",
    version="0.2.0",
)


def schedule_text(settings: BeerSettings) -> str:
    if not settings.daily:
        return "выключена"
    when = f"каждый день в {settings.hour:02d}:{settings.minute:02d}"
    return when if settings.channel_id else f"{when}, но канал не задан — не отправляется"


def create_plugin(nats_url: str = "nats://localhost:4222") -> Plugin:
    plugin = Plugin(SERVICE, nats_url=nats_url)
    beer = BeerService(plugin.discord, BeerSettings.load())
    plugin.add_lifespan(beer)

    @plugin.command(Command(name="beer", description="Узнать цену на пиво", tag="beer"))
    async def beer_command(cmd: ExecutedCommand) -> ExecutedCommandResponse:
        return ExecutedCommandResponse(message=await beer.refresh_price(), is_final=True)

    # ------------------------------------------------------------------
    # Страница в веб-панели
    # ------------------------------------------------------------------

    @plugin.panel_page("beer", title="Пивная биржа", icon="🍺")
    async def beer_page(ctx: PanelContext) -> PanelPage:
        settings = beer.settings
        if beer.price is not None:
            headline = Text(f"{beer.price:.2f} ₽ за литр {beer_utils.price_arrow(beer.price, beer.prev_price)}", style="title")
        else:
            headline = Text("Цену ещё не проверяли с запуска плагина", style="muted")

        return PanelPage(blocks=[
            headline,
            KeyValue(items={
                "Прошлая цена": f"{beer.prev_price:.2f} ₽" if beer.prev_price is not None else "—",
                "Проверено": beer.checked_at.strftime("%d.%m %H:%M") if beer.checked_at else "—",
                "Рассылка": schedule_text(settings),
                "Следующая отправка": beer.next_run.strftime("%d.%m %H:%M") if beer.next_run else "—",
            }),
            Button(action="refresh", label="Обновить цену", style="primary"),
            Button(action="send_now", label="Отправить в канал", confirm="Отправить цену в канал сейчас?"),
            Form(action="save", submit="Сохранить настройки", fields=[
                ChannelPicker(name="channel_id", label="Канал рассылки", value=settings.channel_id),
                Toggle(name="daily", label="Ежедневная рассылка", value=settings.daily),
                NumberField(name="hour", label="Час", value=settings.hour, min=0, max=23, step=1),
                NumberField(name="minute", label="Минута", value=settings.minute, min=0, max=59, step=1),
            ]),
            Link(url=beer_utils.URL, label="Откуда берётся цена"),
        ])

    @plugin.panel_action("refresh")
    async def refresh(ctx: PanelContext, values: dict) -> str:
        await beer.refresh_price()
        if beer.price is None:
            raise ValueError("Не удалось получить цену с сайта")
        return f"Цена обновлена: {beer.price:.2f} ₽"

    @plugin.panel_action("send_now")
    async def send_now(ctx: PanelContext, values: dict) -> str:
        await beer.send_to_channel()
        return "Цена отправлена в канал"

    @plugin.panel_action("save")
    async def save(ctx: PanelContext, values: dict) -> str:
        beer.update_settings(
            channel_id=values.get("channel_id"),   # выбор канала приходит числом или None
            daily=bool(values.get("daily")),
            hour=int(values.get("hour") or 0),
            minute=int(values.get("minute") or 0),
        )
        return "Настройки сохранены"

    return plugin


def run() -> None:
    load_dotenv()
    create_plugin(os.getenv("NATS_URL", "nats://localhost:4222")).run()


if __name__ == "__main__":
    run()
