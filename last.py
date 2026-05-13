import json
import time
import os
import hashlib
import requests
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from bs4 import BeautifulSoup
from urllib.parse import urljoin

import pytz

FIREBASE_URL = os.getenv("FIREBASE_URL")

# =========================
# DATE
# =========================

def get_date():
    tz = pytz.timezone("Asia/Riyadh")
    return datetime.now(tz).strftime("%Y-%m-%d")


def get_matches_url():
    return f"https://www.kooora.com/كرة-القدم/مواعيد-المباريات/{get_date()}"


# =========================
# ID GENERATOR
# =========================

def generate_match_id(home, away, league):
    raw = f"{home}_{away}_{league}"
    return hashlib.md5(raw.encode()).hexdigest()


# =========================
# FIREBASE HELPERS
# =========================

def firebase_get(path):
    url = f"{FIREBASE_URL}/{path}.json"

    try:
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            return response.json()

    except:
        pass

    return None


def firebase_patch(path, data):
    url = f"{FIREBASE_URL}/{path}.json"

    response = requests.patch(url, json=data, timeout=20)

    print(response.status_code)


# =========================
# SCRAPER
# =========================

def extract_matches(soup):

    json_matches = {}

    scripts = soup.find_all(
        "script",
        type="application/ld+json"
    )

    for script in scripts:

        try:

            if not script.string:
                continue

            data = json.loads(script.string)

            if (
                isinstance(data, dict)
                and data.get("@type") == "SportsEvent"
            ):

                url = data.get("url", "")

                json_matches[url] = {

                    "home_logo":
                        data.get("homeTeam", {})
                            .get("logo", ""),

                    "away_logo":
                        data.get("awayTeam", {})
                            .get("logo", "")
                }

        except:
            continue

    leagues = {}

    headers = soup.find_all(
        "a",
        class_="fco-competition-section__header"
    )

    for header in headers:

        name_elem = header.find(
            "span",
            class_="fco-competition-section__header-name"
        )

        if not name_elem:
            continue

        name = name_elem.get_text().strip()

        img = header.find(
            "img",
            class_="fco-image__image"
        )

        logo = img["src"] if img and img.get("src") else ""

        leagues[name] = logo

    matches = []

    items = soup.find_all(
        "div",
        class_="fco-match-list-item"
    )

    for item in items:

        link = ""

        a = item.find(
            "a",
            class_="fco-match-data"
        )

        if a and a.get("href"):

            link = urljoin(
                "https://www.kooora.com",
                a["href"]
            )

        league_name = "Unknown"
        league_logo = ""

        section = item.find_parent(
            "div",
            class_="match-list_livescores-match-list__section__n742K"
        )

        if section:

            header = section.find(
                "a",
                class_="fco-competition-section__header"
            )

            if header:

                league_elem = header.find(
                    "span",
                    class_="fco-competition-section__header-name"
                )

                if league_elem:

                    league_name = league_elem.get_text().strip()

                    league_logo = leagues.get(
                        league_name,
                        ""
                    )

        status = "لم تبدأ"

        data_status = item.get(
            "data-match-status",
            ""
        )

        if data_status == "LIVE":
            status = "مباشر"

        elif data_status == "RESULT":
            status = "انتهت"

        score = ""

        score_home = item.find(
            "span",
            class_="fco-match-score-home"
        )

        score_away = item.find(
            "span",
            class_="fco-match-score-away"
        )

        if score_home and score_away:

            score = (
                f"{score_home.get_text().strip()} - "
                f"{score_away.get_text().strip()}"
            )

        minute = ""

        minute_elem = item.find(
            "div",
            class_="fco-match-minutes__value"
        )

        if minute_elem:
            minute = minute_elem.get_text().strip()

        time_text = ""

        time_elem = item.find(
            "time",
            class_="fco-match-start-time"
        )

        if time_elem:
            time_text = time_elem.get_text().strip()

        home = "Unknown"
        away = "Unknown"

        home_elem = item.find(
            "span",
            class_="fco-team-name"
        )

        teams = item.find_all(
            "span",
            class_="fco-team-name"
        )

        if len(teams) >= 2:

            home = teams[0].get_text().strip()
            away = teams[1].get_text().strip()

        logos = json_matches.get(link, {})

        channels = []

        for ch in item.find_all(
            "div",
            class_="fco-tv-channel__name"
        ):

            name = ch.get_text().strip()

            if name not in channels:
                channels.append(name)

        match_id = generate_match_id(
            home,
            away,
            league_name
        )

        matches.append({

            "id": match_id,

            "static": {

                "league":
                    league_name,

                "league_logo":
                    league_logo,

                "home_team":
                    home,

                "home_logo":
                    logos.get(
                        "home_logo",
                        ""
                    ),

                "away_team":
                    away,

                "away_logo":
                    logos.get(
                        "away_logo",
                        ""
                    ),

                "channel":
                    channels,

                "time":
                    time_text
            },

            "live": {

                "status":
                    status,

                "score":
                    score,

                "minute":
                    minute
            }
        })

    return matches


# =========================
# UPDATE ONLY LIVE DATA
# =========================

def upload_matches(matches):

    date = get_date()

    for match in matches:

        match_id = match["id"]

        static_path = (
            f"matches/{date}/{match_id}/static"
        )

        live_path = (
            f"matches/{date}/{match_id}/live"
        )

        old_static = firebase_get(static_path)

        # رفع البيانات الثابتة مرة واحدة فقط
        if not old_static:

            firebase_patch(
                static_path,
                match["static"]
            )

        # تحديث live دائماً
        firebase_patch(
            live_path,
            match["live"]
        )

    print(f"✅ Uploaded {len(matches)} matches")


# =========================
# MAIN
# =========================

def scrape():

    options = Options()

    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(
        service=Service(
            ChromeDriverManager().install()
        ),
        options=options
    )

    try:

        url = get_matches_url()

        print("Scraping:", url)

        driver.get(url)

        time.sleep(10)

        soup = BeautifulSoup(
            driver.page_source,
            "html.parser"
        )

        matches = extract_matches(soup)

        upload_matches(matches)

    finally:

        driver.quit()


if __name__ == "__main__":
    scrape()
