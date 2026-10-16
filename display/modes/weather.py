"""Weather + calendar mode."""

from __future__ import annotations

import calendar
import datetime
import os
import socket
import struct
import time

import requests
from PIL import Image, ImageDraw, ImageFont
from rgbmatrix import RGBMatrix, graphics

from display.config import load_secrets
from display.matrix import CANVAS_H, CANVAS_W
from display.modes.compact_weather import WeatherReading, render_compact_weather
from display.pillow_compat import set_pillow_image

WEATHER_REFRESH_SECONDS = 300
FONT_PATH = os.path.normpath(
    os.path.join(
        os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra"),
        "repos/rpi-rgb-led-matrix/fonts/6x10.bdf",
    )
)


def _fetch_weather(api_key: str, city: str) -> dict | None:
    url = (
        f"http://api.openweathermap.org/data/2.5/weather"
        f"?q={city}&appid={api_key}&units=imperial"
    )
    try:
        response = requests.get(url, timeout=10)
    except requests.RequestException as exc:
        print(f"Weather API error: {exc}")
        return None
    if response.status_code != 200:
        print(f"Weather API HTTP {response.status_code}")
        return None
    return response.json()


def _get_weather(api_key: str, city: str):
    data = _fetch_weather(api_key, city)
    if data is None:
        return ("Weather data not available", "", "", "", "", "")
    temp = data["main"]["temp"]
    temp_max = data["main"]["temp_max"]
    temp_min = data["main"]["temp_min"]
    feelslike = data["main"]["feels_like"]
    conditions = data["weather"][0]["description"]
    humidity = data["main"]["humidity"]
    return (
        f"Conditions: {conditions.capitalize()}",
        f"Temp: {temp}f",
        f"Max Temp: {temp_max}f",
        f"Min Temp: {temp_min}f",
        f"Feels Like: {feelslike}f",
        f"Humidity: {humidity}%",
    )


def _safe_get_weather(api_key: str, city: str):
    try:
        return _get_weather(api_key, city)
    except (KeyError, IndexError, ValueError) as exc:
        print(f"Weather API bad payload: {exc}")
        return ("Weather data not available", "", "", "", "", "")


def _safe_reading(api_key: str, city: str) -> WeatherReading | None:
    data = _fetch_weather(api_key, city)
    try:
        return WeatherReading.from_openweathermap(data) if data else None
    except (KeyError, IndexError, ValueError) as exc:
        print(f"Weather API bad payload: {exc}")
        return None


def _request_time_from_ntp(addr: str):
    ref_time_1970 = 2208988800
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.settimeout(1.0)
    try:
        timedata = b"\x1b" + 47 * b"\0"
        client.sendto(timedata, (addr, 123))
        timedata, _address = client.recvfrom(1024)
        if timedata:
            t = struct.unpack("!12I", timedata)[10]
            t -= ref_time_1970
            return time.ctime(t), t
    except socket.timeout:
        print("[WARN] NTP timeout")
    except OSError as exc:
        print(f"[ERR] NTP failure: {exc}")
    finally:
        client.close()
    return time.ctime(), time.time()


def _safe_ntp_time(addr: str):
    try:
        return _request_time_from_ntp(addr)
    except OSError as exc:
        print(f"NTP error: {exc}")
        return time.ctime(), time.time()


def _generate_calendar(year: int, month: int) -> Image.Image:
    image = Image.new("RGB", (192, 64), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    month_calendar = calendar.monthcalendar(year, month)
    current_day = datetime.datetime.now().day
    font = ImageFont.load_default()
    cell_width = 24
    cell_height = 8
    start_x = 3
    start_y = 3

    days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i, day in enumerate(days_of_week):
        draw.text((start_x + i * cell_width, start_y), day, font=font, fill=(255, 255, 255))

    for week_num, week in enumerate(month_calendar):
        for day_num, day in enumerate(week):
            if day == 0:
                continue
            x_pos = start_x + day_num * cell_width
            y_pos = start_y + (week_num + 1) * cell_height
            if day == current_day:
                draw.rectangle(
                    [x_pos, y_pos, x_pos + cell_width, y_pos + cell_height],
                    fill=(255, 0, 0),
                )
                draw.text((x_pos, y_pos), str(day), font=font, fill=(255, 255, 255))
            else:
                draw.text((x_pos, y_pos), str(day), font=font, fill=(255, 255, 255))
    return image


class WeatherMode:
    tick_interval = 0.15

    def setup(self, matrix: RGBMatrix) -> None:
        secrets = load_secrets()
        self._api_key = secrets["openweathermap_api_key"]
        self._city = secrets["city"]
        self._ntp_server = secrets.get("ntp_server", "")
        self._compact = (CANVAS_W, CANVAS_H) != (192, 192)
        if self._compact:
            # Clock comes from the system (chrony); only the minute is shown.
            self.tick_interval = 1.0
            self._reading = _safe_reading(self._api_key, self._city)
            self._last_weather_update = time.time()
            return

        self._font = graphics.Font()
        self._font.LoadFont(FONT_PATH)

        (
            self._desc_text,
            self._temp_text,
            self._temp_max_text,
            self._temp_min_text,
            self._feelslike_text,
            self._humidity_text,
        ) = _safe_get_weather(self._api_key, self._city)
        self._last_weather_update = time.time()

        self._white = graphics.Color(255, 255, 255)
        self._red = graphics.Color(255, 0, 0)
        self._blue = graphics.Color(0, 0, 255)
        self._purple = graphics.Color(255, 0, 255)
        self._orange = graphics.Color(255, 165, 0)
        self._green = graphics.Color(0, 255, 0)
        self._line = graphics.Color(100, 100, 100)

    def teardown(self) -> None:
        pass

    def _tick_compact(self, matrix: RGBMatrix, canvas):
        if time.time() - self._last_weather_update >= WEATHER_REFRESH_SECONDS:
            reading = _safe_reading(self._api_key, self._city)
            if reading is not None:
                self._reading = reading
            self._last_weather_update = time.time()
        frame = render_compact_weather(datetime.datetime.now(), self._reading,
                                       CANVAS_W, CANVAS_H)
        set_pillow_image(canvas, frame)
        return matrix.SwapOnVSync(canvas)

    def tick(self, matrix: RGBMatrix, canvas):
        if self._compact:
            return self._tick_compact(matrix, canvas)
        if time.time() - self._last_weather_update >= WEATHER_REFRESH_SECONDS:
            (
                self._desc_text,
                self._temp_text,
                self._temp_max_text,
                self._temp_min_text,
                self._feelslike_text,
                self._humidity_text,
            ) = _safe_get_weather(self._api_key, self._city)
            self._last_weather_update = time.time()

        canvas.Clear()

        ntp_time, _ = _safe_ntp_time(self._ntp_server)
        graphics.DrawText(canvas, self._font, 5, 10, self._white, ntp_time)
        graphics.DrawText(canvas, self._font, 10, 95, self._blue, self._desc_text)
        graphics.DrawText(canvas, self._font, 10, 105, self._white, self._temp_text)
        graphics.DrawText(canvas, self._font, 10, 115, self._purple, self._temp_max_text)
        graphics.DrawText(canvas, self._font, 10, 125, self._orange, self._temp_min_text)
        graphics.DrawText(canvas, self._font, 10, 135, self._red, self._feelslike_text)
        graphics.DrawText(canvas, self._font, 10, 145, self._green, self._humidity_text)

        graphics.DrawLine(canvas, 0, 15, 383, 15, self._line)
        graphics.DrawLine(canvas, 0, 85, 383, 85, self._line)

        now = datetime.datetime.now()
        calendar_image = _generate_calendar(now.year, now.month)
        set_pillow_image(canvas, calendar_image, 0, 18)
        return matrix.SwapOnVSync(canvas)
