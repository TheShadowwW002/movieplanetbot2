#!/usr/bin/env python3
"""
Bot di notifica Telegram per il sito MoviePlanet Vercelli.

Cosa fa:
- scarica periodicamente la pagina della programmazione
- estrae film -> giorni -> orari
- confronta con l'ultimo stato salvato (file JSON)
- se trova film nuovi, giorni nuovi o orari nuovi, manda un messaggio Telegram
"""

import os
import re
import json
import time
import logging

import requests
from bs4 import BeautifulSoup

# ------------------- CONFIGURAZIONE -------------------

BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "INSERISCI_IL_TUO_BOT_TOKEN")
CHAT_ID = os.environ.get("TG_CHAT_ID", "INSERISCI_IL_TUO_CHAT_ID")

URL = "https://www.movieplanetgroup.it/mp_vercelli/index.php"

POLL_INTERVAL_SECONDS = 180

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mp_state.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mp_bot.log")

DAYS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("movieplanet_bot")


def send_telegram_message(text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True}
    try:
        r = requests.post(url, data=payload, timeout=15)
        if not r.ok:
            log.error("Errore invio Telegram: %s - %s", r.status_code, r.text)
    except requests.RequestException as e:
        log.error("Eccezione invio Telegram: %s", e)


def fetch_html() -> str:
    r = requests.get(URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def parse_programmazione(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    films = {}
    current_film = None
    current_day = None
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("Regia:") and i > 0:
            title = lines[i - 1]
            title = re.sub(r"^(NEW!|NUOVO!)\s*", "", title).strip()
            current_film = title
            films.setdefault(current_film, {})
            current_day = None

        elif line in DAYS and current_film is not None:
            current_day = line
            films[current_film].setdefault(current_day, [])

        elif current_film is not None and current_day is not None and re.fullmatch(
            r"(\d{2}:\d{2})+", line
        ):
            times = re.findall(r"\d{2}:\d{2}", line)
            films[current_film][current_day] = sorted(set(times))
            current_day = None

        i += 1

    return films


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            log.warning("State file corrotto, riparto da zero.")
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def diff_and_notify(old: dict, new: dict) -> None:
    messages = []

    for film, days in new.items():
        if film not in old:
            orari_str = "; ".join(f"{d}: {', '.join(t)}" for d, t in days.items())
            messages.append(f"🎬 NUOVO FILM IN PROGRAMMAZIONE: {film}\n{orari_str}")
            continue

        for day, times in days.items():
            old_times = set(old[film].get(day, []))
            new_times = set(times)

            if day not in old[film]:
                messages.append(
                    f"📅 Nuova data per \"{film}\": {day} -> {', '.join(sorted(new_times))}"
                )
            else:
                added = new_times - old_times
                if added:
                    messages.append(
                        f"🕒 Nuovo/i orario/i per \"{film}\" ({day}): {', '.join(sorted(added))}"
                    )

    for msg in messages:
        log.info("Notifica: %s", msg)
        send_telegram_message(msg)

    if not messages:
        log.info("Nessuna novità.")


def run_once() -> dict:
    html = fetch_html()
    new_state = parse_programmazione(html)
    old_state = load_state()

    if old_state:
        diff_and_notify(old_state, new_state)
    else:
        log.info("Primo avvio: salvo lo stato iniziale senza notificare.")

    save_state(new_state)
    return new_state


def main():
    if "INSERISCI" in BOT_TOKEN or "INSERISCI" in CHAT_ID:
        log.error(
            "Devi impostare BOT_TOKEN e CHAT_ID prima di partire."
        )
        return

    if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("RUN_ONCE") == "1":
        try:
            run_once()
        except Exception as e:
            log.exception("Errore durante il controllo: %s", e)
            raise
        return

    log.info("Bot avviato. Controllo ogni %s secondi.", POLL_INTERVAL_SECONDS)
    while True:
        try:
            run_once()
        except Exception as e:
            log.exception("Errore durante il controllo: %s", e)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
