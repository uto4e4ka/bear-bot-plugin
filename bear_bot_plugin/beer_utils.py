import asyncio

import requests
from bs4 import BeautifulSoup

from bear_bot_plugin.config import data_file

URL = "https://sampivo-opt.ru/tovar/pivo-samarskoe-keg-tsena-za-1-litr/"
PRICE_FILE = "prev_price.txt"   # в папке данных плагина


# ======== Парсинг цены пива ========
def get_beer_price() -> float | None:
    try:
        response = requests.get(URL, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        price_meta = soup.find("meta", {"itemprop": "price"})
        if price_meta:
            return float(price_meta["content"])
        price_span = soup.find("span", class_="amount")
        if price_span:
            text = price_span.text.strip().replace("руб.", "").replace(",", ".").strip()
            return float(text)
        return None
    except Exception:
        return None


async def fetch_beer_price() -> float | None:
    """То же, что get_beer_price, но не блокирует event loop плагина на время запроса."""
    return await asyncio.to_thread(get_beer_price)


# ======== Работа с файлом предыдущей цены ========
def read_prev_price() -> float | None:
    path = data_file(PRICE_FILE)
    if path.exists():
        try:
            return float(path.read_text().strip())
        except Exception:
            return None
    return None


def write_prev_price(price: float) -> None:
    data_file(PRICE_FILE).write_text(str(price))


# ======== Формирование “биржевого” сообщения ========
def price_arrow(current: float, prev: float | None) -> str:
    if prev is None or current == prev:
        return "➡️"
    return "📈" if current > prev else "📉"


def format_price_message(current: float | None, prev: float | None) -> str:
    if current is None:
        return "Не удалось получить цену пива 😢"
    return f"**🍺 Текущее пиво:** Жигулевское\n**Цена за 1 литр:** {current:.2f} руб. {price_arrow(current, prev)}"


async def build_price_message() -> str:
    current_price = await fetch_beer_price()
    if current_price is None:
        return format_price_message(None, None)

    prev_price = read_prev_price()
    write_prev_price(current_price)  # обновляем файл
    return format_price_message(current_price, prev_price)
