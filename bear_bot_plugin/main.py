import os

from dotenv import load_dotenv
from potehinsonnet import Plugin
from potehinsonnet.net_models.discord_models import Command, CommandArgument, ExecutedCommand, \
    ExecutedCommandResponse
from potehinsonnet.net_models.panel_ui import (
    Button,
    ChannelPicker,
    Form,
    ItemList,
    KeyValue,
    Link,
    ListItem,
    NumberField,
    PanelContext,
    PanelPage,
    Text,
    TextField,
    Toggle,
)
from potehinsonnet.net_models.system_models import Service

from bear_bot_plugin import beer_utils
from bear_bot_plugin.config import PLUGIN_NAME, BeerSettings
from bear_bot_plugin.core import TIMEZONE, BeerService
from bear_bot_plugin.events import EventService

SERVICE = Service(
    name=PLUGIN_NAME,
    label="🍺 Пивная биржа",
    description="Цена пива, ежедневная рассылка и события с обратным отсчётом",
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
    events = EventService(plugin.discord, TIMEZONE)
    plugin.add_lifespan(events)

    @plugin.command(Command(name="beer", description="Узнать цену на пиво", tag="beer"))
    async def beer_command(cmd: ExecutedCommand) -> ExecutedCommandResponse:
        return ExecutedCommandResponse(message=await beer.refresh_price(), is_final=True)

    # ------------------------------------------------------------------
    # События: /event add, /event list, /event delete
    # ------------------------------------------------------------------

    def arg(cmd: ExecutedCommand, name: str) -> str:
        return next((a.value for a in cmd.args if a.name == name), "")

    @plugin.command(Command(
        name="add", group="event", tag="event_add", permission="bear.events",
        description="Запланировать событие с обратным отсчётом",
        args=[
            CommandArgument(name="name", description="Что будет, например: Концерт Доры"),
            CommandArgument(name="date", description="Дата: 20.11.2026 или 20.11"),
            CommandArgument(name="time", description="Время: 19:00"),
            CommandArgument(name="daily", type="bool", required=False, default=False,
                            description="Напоминать каждый день, сколько осталось"),
        ],
    ))
    async def event_add(cmd: ExecutedCommand) -> ExecutedCommandResponse:
        try:
            event = events.add(
                name=arg(cmd, "name"), date=arg(cmd, "date"), time=arg(cmd, "time"),
                channel_id=cmd.channel.id,  # напоминать туда, где запланировали
                daily=arg(cmd, "daily").lower() == "true", created_by=cmd.user.display_name or cmd.user.name,
            )
        except ValueError as e:
            return ExecutedCommandResponse(message=f"❌ {e}", is_final=True)
        reminders = f"каждый день в {event.daily_hour:02d}:00, " if event.daily else ""
        return ExecutedCommandResponse(ephemeral=False, is_final=True, message=(
            f"📅 Запланировано!\n{events.countdown_text(event)}\n"
            f"-# Напомню здесь: {reminders}за неделю, за 3 дня, за день, за час и в момент начала"
        ))

    @plugin.command(Command(
        name="list", group="event", tag="event_list", description="Сколько осталось до событий",
    ))
    async def event_list(cmd: ExecutedCommand) -> ExecutedCommandResponse:
        upcoming = events.upcoming()
        if not upcoming:
            return ExecutedCommandResponse(is_final=True, message="Событий пока нет — `/event add`")
        return ExecutedCommandResponse(ephemeral=False, is_final=True,
                                       message="\n".join(events.countdown_text(e) for e in upcoming))

    @plugin.command(Command(
        name="delete", group="event", tag="event_delete", permission="bear.events",
        description="Отменить событие",
        args=[CommandArgument(name="name", description="Название события")],
    ))
    async def event_delete(cmd: ExecutedCommand) -> ExecutedCommandResponse:
        event = events.find(arg(cmd, "name"))
        if event is None:
            return ExecutedCommandResponse(is_final=True, message="❌ Такого события нет — посмотри `/event list`")
        events.delete(event.id)
        return ExecutedCommandResponse(ephemeral=False, is_final=True, message=f"🗑️ «{event.name}» отменено")

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

    @plugin.panel_page("events", title="События", icon="📅")
    async def events_page(ctx: PanelContext) -> PanelPage:
        items = []
        for e in events.upcoming():
            next_at = events.next_reminder(e)
            items.append(ListItem(
                title=f"{e.name} — {e.when.astimezone(TIMEZONE):%d.%m.%Y %H:%M}",
                subtitle=" · ".join(filter(None, [
                    e.description,
                    events.countdown_text(e).split("\n")[0].replace("**", ""),
                    f"каждый день в {e.daily_hour:02d}:00" if e.daily else "",
                    f"следующее напоминание {next_at:%d.%m %H:%M}" if next_at else "",
                ])),
                actions=[
                    Button(action="event_remind", label="Напомнить сейчас", values={"event_id": e.id}),
                    Button(action="event_delete", label="Удалить", style="danger",
                           confirm=f"Отменить «{e.name}»?", values={"event_id": e.id}),
                ],
            ))
        return PanelPage(blocks=[
            ItemList(items=items, empty="Событий пока нет.", max_visible=6),
            Text("Новое событие", style="title"),
            Text("Напомню в канале за неделю, за 3 дня, за день, за час и в момент начала. "
                 "Ежедневный отсчёт — по желанию.", style="muted"),
            Form(action="event_add", submit="Запланировать", fields=[
                TextField(name="name", label="Событие", placeholder="Например: Концерт Доры", required=True),
                TextField(name="description", label="Описание", placeholder="Где, что взять с собой…"),
                TextField(name="date", label="Дата", placeholder="20.11.2026", required=True),
                TextField(name="time", label="Время", value="19:00", required=True),
                ChannelPicker(name="channel_id", label="Канал для напоминаний", value=beer.settings.channel_id),
                Toggle(name="daily", label="Каждый день писать, сколько осталось"),
                NumberField(name="daily_hour", label="Во сколько (час)", value=12, min=0, max=23, step=1),
            ]),
        ])

    @plugin.panel_action("event_add")
    async def panel_event_add(ctx: PanelContext, values: dict) -> str:
        event = events.add(
            name=str(values.get("name") or ""), date=str(values.get("date") or ""),
            time=str(values.get("time") or ""), channel_id=values.get("channel_id"),
            description=str(values.get("description") or ""), daily=bool(values.get("daily")),
            daily_hour=int(values.get("daily_hour") or 0), created_by=ctx.user.name,
        )
        return f"«{event.name}» запланировано"

    @plugin.panel_action("event_remind")
    async def panel_event_remind(ctx: PanelContext, values: dict) -> str:
        event = await events.remind_now(str(values.get("event_id") or ""))
        return f"Напомнили про «{event.name}»"

    @plugin.panel_action("event_delete")
    async def panel_event_delete(ctx: PanelContext, values: dict) -> str:
        event = events.delete(str(values.get("event_id") or ""))
        return f"«{event.name}» отменено"

    return plugin


def run() -> None:
    load_dotenv()
    create_plugin(os.getenv("NATS_URL", "nats://localhost:4222")).run()


if __name__ == "__main__":
    run()
