
from datetime import time
import requests
from bs4 import BeautifulSoup
import os






URL = "https://sampivo-opt.ru/tovar/pivo-samarskoe-keg-tsena-za-1-litr/"
PRICE_FILE = "prev_price.txt"

# ======== Парсинг цены пива ========
def get_beer_price():
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

# ======== Работа с файлом предыдущей цены ========
def read_prev_price():
    if os.path.exists(PRICE_FILE):
        try:
            with open(PRICE_FILE, "r") as f:
                return float(f.read().strip())
        except Exception:
            return None
    return None

def write_prev_price(price):
    with open(PRICE_FILE, "w") as f:
        f.write(str(price))

# ======== Формирование “биржевого” сообщения ========
def build_price_message():
    current_price = get_beer_price()
    if current_price is None:
        return "Не удалось получить цену пива 😢"

    prev_price = read_prev_price()
    write_prev_price(current_price)  # обновляем файл

    # Определяем стрелку
    if prev_price is None:
        arrow = "➡️"  # первый раз
    elif current_price > prev_price:
        arrow = "📈"
    elif current_price < prev_price:
        arrow = "📉"
    else:
        arrow = "➡️"

    return f"**🍺 Текущее пиво:** Жигулевское\n**Цена за 1 литр:** {current_price:.2f} руб. {arrow}"

# ======== Ежедневное сообщение ========
@tasks.loop(time=time(hour=12, minute=0))
async def daily_message():
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await channel.send(build_price_message())

