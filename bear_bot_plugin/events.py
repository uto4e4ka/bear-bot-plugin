"""Запланированные события с обратным отсчётом: «Концерт Доры — осталось 12 дней».

Напоминания уходят в канал события: за неделю, за 3 дня, за день, за час и в момент начала,
плюс, если включено, каждый день в выбранный час. Прошедшие события удаляются сами.
"""
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from potehinsonnet.discord_provider import DiscordProvider
from potehinsonnet.net_models.discord_models import NatsMessage

from bear_bot_plugin.config import PLUGIN_NAME, data_file

# Когда напомнить до начала; 0 — в момент начала
MILESTONES = [timedelta(days=7), timedelta(days=3), timedelta(days=1), timedelta(hours=1), timedelta(0)]


def plural(n: int, one: str, few: str, many: str) -> str:
    """1 день, 2 дня, 5 дней."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def format_left(left: timedelta) -> str:
    """«12 дней 5 часов», «3 часа 20 минут», «15 минут»."""
    minutes = max(0, int(left.total_seconds() // 60))
    days, hours, mins = minutes // 1440, minutes % 1440 // 60, minutes % 60
    parts = []
    if days:
        parts.append(f"{days} {plural(days, 'день', 'дня', 'дней')}")
    if hours:
        parts.append(f"{hours} {plural(hours, 'час', 'часа', 'часов')}")
    if mins and not days:  # с днями минуты уже не важны
        parts.append(f"{mins} {plural(mins, 'минута', 'минуты', 'минут')}")
    return " ".join(parts[:2]) or "меньше минуты"


def parse_when(date: str, time: str, tz, now: datetime | None = None) -> datetime:
    """«20.11.2026» или «20.11» (ближайшее такое число) и «19:00» → время события."""
    now = now or datetime.now(tz)
    try:
        hour, minute = (int(x) for x in time.strip().replace(".", ":").split(":"))
        parts = [int(x) for x in date.strip().replace("/", ".").replace("-", ".").split(".")]
        if len(parts) == 3:
            day, month, year = parts
            if year < 100:
                year += 2000
            when = datetime(year, month, day, hour, minute, tzinfo=tz)
        elif len(parts) == 2:
            day, month = parts
            when = datetime(now.year, month, day, hour, minute, tzinfo=tz)
            if when <= now:
                when = when.replace(year=now.year + 1)
        else:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Дата — ДД.ММ.ГГГГ или ДД.ММ, время — ЧЧ:ММ, например 20.11.2026 и 19:00")
    if when <= now:
        raise ValueError("Это время уже прошло")
    return when


@dataclass
class Event:
    id: str
    name: str
    at: str                      # время события, ISO с часовым поясом
    channel_id: int
    description: str = ""
    daily: bool = False          # отсчёт каждый день
    daily_hour: int = 12
    created_by: str = ""

    @property
    def when(self) -> datetime:
        return datetime.fromisoformat(self.at)


@dataclass
class EventService:
    """Хранит события и напоминания в планировщике. Запускается вместе с плагином (lifespan)."""
    discord: DiscordProvider
    tz: object
    file: Path = field(default_factory=lambda: data_file("events.json"))   # в папке данных плагина
    scheduler: AsyncIOScheduler = None
    events: list[Event] = field(default_factory=list)

    def __post_init__(self):
        self.scheduler = self.scheduler or AsyncIOScheduler(timezone=self.tz)
        self.events = self._load()

    async def __aenter__(self):
        self._drop_past()
        for event in self.events:
            self._schedule(event)
        self.scheduler.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.scheduler.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Хранение
    # ------------------------------------------------------------------

    def _load(self) -> list[Event]:
        if not self.file.exists():
            return []
        try:
            return [Event(**e) for e in json.loads(self.file.read_text(encoding="utf-8"))]
        except (ValueError, TypeError):
            return []

    def _save(self) -> None:
        self.file.write_text(json.dumps([asdict(e) for e in self.events], ensure_ascii=False, indent=2),
                             encoding="utf-8")

    def _drop_past(self) -> None:
        now = datetime.now(self.tz)
        self.events = [e for e in self.events if e.when > now]
        self._save()

    def upcoming(self) -> list[Event]:
        self._drop_past()
        return sorted(self.events, key=lambda e: e.when)

    def find(self, query: str) -> Event | None:
        query = query.strip().lower()
        return next((e for e in self.upcoming() if e.id == query or e.name.lower() == query), None) or \
            next((e for e in self.upcoming() if query and query in e.name.lower()), None)

    def add(self, name: str, date: str, time: str, channel_id: int | None, description: str = "",
            daily: bool = False, daily_hour: int = 12, created_by: str = "") -> Event:
        name = name.strip()
        if not name:
            raise ValueError("Как называется событие?")
        if not channel_id:
            raise ValueError("Выберите канал для напоминаний")
        if not 0 <= daily_hour <= 23:
            raise ValueError("Час ежедневного отсчёта — от 0 до 23")
        when = parse_when(date, time, self.tz)
        event = Event(id=uuid.uuid4().hex[:6], name=name, at=when.isoformat(), channel_id=int(channel_id),
                      description=description.strip(), daily=daily, daily_hour=daily_hour, created_by=created_by)
        self.events.append(event)
        self._save()
        self._schedule(event)
        return event

    def delete(self, event_id: str) -> Event:
        event = next((e for e in self.events if e.id == event_id), None)
        if event is None:
            raise ValueError("Событие не найдено")
        self._unschedule(event)
        self.events = [e for e in self.events if e.id != event_id]
        self._save()
        return event

    # ------------------------------------------------------------------
    # Напоминания
    # ------------------------------------------------------------------

    def _job_ids(self, event: Event) -> list[str]:
        return [f"event:{event.id}:m{i}" for i in range(len(MILESTONES))] + [f"event:{event.id}:daily"]

    def _unschedule(self, event: Event) -> None:
        for job_id in self._job_ids(event):
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

    def _schedule(self, event: Event) -> None:
        self._unschedule(event)
        now = datetime.now(self.tz)
        for i, before in enumerate(MILESTONES):
            run_at = event.when - before
            if run_at > now:
                self.scheduler.add_job(self.remind, "date", run_date=run_at, args=[event.id, i == len(MILESTONES) - 1],
                                       id=f"event:{event.id}:m{i}")
        if event.daily:
            self.scheduler.add_job(self.remind, "cron", hour=event.daily_hour, minute=0, args=[event.id, False],
                                   id=f"event:{event.id}:daily", end_date=event.when)

    def next_reminder(self, event: Event) -> datetime | None:
        times = [job.next_run_time for job_id in self._job_ids(event)
                 if (job := self.scheduler.get_job(job_id)) and job.next_run_time]
        return min(times) if times else None

    def countdown_text(self, event: Event, now: datetime | None = None) -> str:
        now = now or datetime.now(self.tz)
        when = event.when.astimezone(self.tz)
        date = when.strftime("%d.%m.%Y в %H:%M")
        if when <= now:
            return f"🎉 **{event.name}** начинается прямо сейчас!"
        left = when - now
        # Название не склоняем («до Концерт Доры»), поэтому — через тире
        if when.date() == now.date():
            head = f"🔥 **{event.name}** — сегодня в {when:%H:%M}, осталось {format_left(left)}!"
        else:
            head = f"⏳ **{event.name}** — осталось {format_left(left)} ({date})"
        return head + (f"\n{event.description}" if event.description else "")

    async def remind(self, event_id: str, final: bool = False) -> None:
        event = next((e for e in self.events if e.id == event_id), None)
        if event is None:
            return
        await self.discord.send_message(NatsMessage(
            service=PLUGIN_NAME, channel_id=event.channel_id,
            text=self.countdown_text(event, now=event.when if final else None),
        ))
        if final:
            self._unschedule(event)
            self.events = [e for e in self.events if e.id != event_id]
            self._save()

    async def remind_now(self, event_id: str) -> Event:
        event = next((e for e in self.events if e.id == event_id), None)
        if event is None:
            raise ValueError("Событие не найдено")
        await self.remind(event_id)
        return event
