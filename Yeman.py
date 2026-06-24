#!/usr/bin/env python3
import json
import re
import os
import hashlib
import requests
import time
import pytz
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
FIREBASE_URL = os.getenv("FIREBASE_URL")
BASE_MATCHES_URL = "https://as-goal.net/wsw/"       # صفحة اليوم الافتراضية
COMMENTATORS_URL = "https://as-goal.net/todays-match-commentators02/"

CHANNEL_MAP = {
    "بي إن سبورت 1": "beIN SPORTS 1",
    "بي إن سبورت 2": "beIN SPORTS 2",
    "بي إن سبورت 3": "beIN SPORTS 3",
    "بي إن سبورت 4": "beIN SPORTS 4",
    "بي إن سبورت 5": "beIN SPORTS 5",
    "بي إن سبورت 6": "beIN SPORTS 6",
    "بي إن سبورت 7": "beIN SPORTS 7",
    "بي إن سبورت 8": "beIN SPORTS 8",
    "يحدد لاحقاً": "TBD",
}

# =========================
# HELPERS & UTILS
# =========================

def get_now_aden():
    return datetime.now(pytz.timezone("Asia/Aden"))

def get_target_dates():
    """
    منطق اختيار التواريخ مطابق لـ OldMatchesRepository.kt:
    - قبل 5 صباحاً   : الأمس + اليوم
    - 5 صباحاً – 5:59 مساءً : اليوم فقط
    - 6 مساءً فما فوق : اليوم + الغد
    """
    now = get_now_aden()
    today_str = now.strftime("%Y-%m-%d")
    hour = now.hour

    if hour < 5:
        yesterday = now - timedelta(days=1)
        return [yesterday.strftime("%Y-%m-%d"), today_str]
    elif hour < 18:
        return [today_str]
    else:
        tomorrow = now + timedelta(days=1)
        return [today_str, tomorrow.strftime("%Y-%m-%d")]

def generate_match_id(home, away, league):
    raw = f"{home}_{away}_{league}"
    return hashlib.md5(raw.encode()).hexdigest()

def league_slug(name):
    slug = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF]+', '-', name.lower())
    return slug.strip('-')

def normalize_text(text):
    if not text: return ""
    text = text.strip()
    text = re.sub(r'[\u064B-\u065F]', '', text)
    text = re.sub(r'[أإآ]', 'ا', text)
    text = re.sub(r'[ة]', 'ه', text)
    text = re.sub(r'[ى]', 'ي', text)
    text = re.sub(r'\s+', ' ', text)
    return text.lower()

# =========================
# FIREBASE HELPERS
# =========================

def firebase_get(path):
    url = f"{FIREBASE_URL}/{path}.json"
    try:
        r = requests.get(url, timeout=10)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def firebase_patch(path, data):
    url = f"{FIREBASE_URL}/{path}.json"
    try:
        r = requests.patch(url, json=data, timeout=20)
        print(f"🔥 Firebase Sync [{path}]: {r.status_code}")
    except Exception as e:
        print(f"❌ Firebase Error: {e}")

# =========================
# SCRAPING LOGIC
# =========================

def extract_commentators(driver):
    driver.get(COMMENTATORS_URL)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".mt-league"))
        )
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        commentators = []
        league_blocks = soup.find_all('div', class_='mt-league')
        for league in league_blocks:
            league_name = league.find('h3').get_text(strip=True) if league.find('h3') else ''
            next_elem = league.find_next_sibling()
            while next_elem and 'mt-league' not in next_elem.get('class', []):
                if 'mt-match' in next_elem.get('class', []):
                    teams = next_elem.find_all('div', class_='mt-team')
                    if len(teams) >= 2:
                        commentators.append({
                            'league': league_name,
                            'home': teams[0].get_text(strip=True),
                            'away': teams[1].get_text(strip=True),
                            'commentator': next_elem.find('div', class_='mt-commentator').get_text(strip=True) if next_elem.find('div', class_='mt-commentator') else '',
                            'channel': next_elem.find('div', class_='mt-channel').get_text(strip=True) if next_elem.find('div', class_='mt-channel') else ''
                        })
                next_elem = next_elem.find_next_sibling()
        return commentators
    except:
        return []

def navigate_to_date(driver, target_date):
    driver.get(BASE_MATCHES_URL)
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".anwp-fl-game"))
    )

    today = get_now_aden().strftime("%Y-%m-%d")
    if target_date == today:
        print("   📍 Already on today's page")
        return

    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    today_dt = datetime.strptime(today, "%Y-%m-%d")
    offset = (target_dt - today_dt).days

    if offset < 0:
        btn_selector = ".anwp-fl-calendar-slider__swiper-button-prev"
        clicks = abs(offset)
    else:
        btn_selector = ".anwp-fl-calendar-slider__swiper-button-next"
        clicks = offset

    print(f"   🔘 Need to click {btn_selector} {clicks} time(s)")
    for i in range(clicks):
        try:
            btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, btn_selector))
            )
            btn.click()
            time.sleep(2.5)
        except Exception as e:
            print(f"   ⚠️ Failed to click {btn_selector}: {e}")
            break

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".anwp-fl-game"))
        )
        print(f"   ✅ Successfully navigated to {target_date}")
    except:
        print(f"   ❌ Could not confirm matches loaded for {target_date}")

def scrape_date(driver, date_str, commentators_list):
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    league_blocks = soup.find_all('div', class_='anwp-fl-block-header')

    if not league_blocks:
        print(f"   ℹ️ No leagues found for {date_str}")
        return

    now_aden_str = get_now_aden().strftime("%Y-%m-%d")

    for header in league_blocks:
        league_name = header.find('a').get_text(strip=True) if header.find('a') else 'Unknown'
        league_logo = header.find('img')['src'] if header.find('img') else ''
        slug = league_slug(league_name)

        firebase_patch(f"leagues/{date_str}/{slug}", {"name": league_name, "logo": league_logo})

        next_elem = header.find_next_sibling()
        while next_elem and 'anwp-fl-block-header' not in next_elem.get('class', []):
            if 'anwp-fl-game' in next_elem.get('class', []):
                home = next_elem.find('div', class_='match-slim__team-home-title').get_text(strip=True)
                away = next_elem.find('div', class_='match-slim__team-away-title').get_text(strip=True)
                h_logo = next_elem.find('img', class_='match-slim__team-home-logo')['src'] if next_elem.find('img', class_='match-slim__team-home-logo') else ''
                a_logo = next_elem.find('img', class_='match-slim__team-away-logo')['src'] if next_elem.find('img', class_='match-slim__team-away-logo') else ''
                m_time = next_elem.find('span', class_='match-slim__time').get_text(strip=True) if next_elem.find('span', class_='match-slim__time') else ''

                h_score = next_elem.find('span', class_='match-slim__scores-home').get_text(strip=True) if next_elem.find('span', class_='match-slim__scores-home') else '-'
                a_score = next_elem.find('span', class_='match-slim__scores-away').get_text(strip=True) if next_elem.find('span', class_='match-slim__scores-away') else '-'

                # تحديد الحالة والدقيقة
                if h_score != '-' and a_score != '-':
                    if date_str == now_aden_str:
                        status = "مباشر"
                        # محاولة جلب الدقيقة
                        minute = ""
                        # قائمة بالمحددات المحتملة
                        minute_selectors = [
                            ('span', 'match-slim__minute'),
                            ('span', 'match-slim__status'),
                            ('div', 'match-slim__minute'),
                            ('div', 'match-slim__status'),
                        ]
                        for tag, cls in minute_selectors:
                            elem = next_elem.find(tag, class_=cls)
                            if elem:
                                text = elem.get_text(strip=True)
                                if text and ("'" in text or text in ["HT", "FT", "ن.ش.1", "ن.ش.2"]):
                                    minute = text
                                    break
                        # في حال لم نجد، نبحث عن أي عنصر يحتوي على '
                        if not minute:
                            import re as regex
                            match = regex.search(r"(\d+\+?\d*'|HT|FT)", next_elem.get_text())
                            if match:
                                minute = match.group(1)
                    else:
                        status = "انتهت"
                        minute = "FT"
                else:
                    status = "لم تبدأ"
                    minute = ""

                # مطابقة المعلق والقناة
                match_comm = "غير مدرج"
                match_chan = "غير مدرج"
                norm_home = normalize_text(home)
                for c in commentators_list:
                    if norm_home == normalize_text(c['home']):
                        match_comm = c['commentator'] if c['commentator'] else "غير مدرج"
                        raw_chan = c['channel'] if c['channel'] else "غير مدرج"
                        match_chan = CHANNEL_MAP.get(raw_chan, raw_chan)
                        break

                match_id = generate_match_id(home, away, league_name)
                match_path = f"matches/{date_str}/{slug}/{match_id}"

                static_data = {
                    "league": league_name,
                    "league_logo": league_logo,
                    "home_team": home,
                    "home_logo": h_logo,
                    "away_team": away,
                    "away_logo": a_logo,
                    "time": m_time
                }
                if not firebase_get(f"{match_path}/static"):
                    firebase_patch(f"{match_path}/static", static_data)

                live_data = {
                    "status": status,
                    "score": f"{h_score} - {a_score}",
                    "channel": [match_chan],
                    "commentator": match_comm,
                    "minute": minute
                }

                existing_live = firebase_get(f"{match_path}/live")
                if existing_live:
                    # تحديث المعلق/القناة إن كانوا غير مدرجين
                    if existing_live.get("commentator") == "غير مدرج" and match_comm != "غير مدرج":
                        live_data["commentator"] = match_comm
                    if existing_live.get("channel") == ["غير مدرج"] and match_chan != "غير مدرج":
                        live_data["channel"] = [match_chan]

                if existing_live != live_data:
                    firebase_patch(f"{match_path}/live", live_data)

            next_elem = next_elem.find_next_sibling()

def main():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        print("📡 Fetching today's commentators list...")
        commentators = extract_commentators(driver)
        print(f"   Found {len(commentators)} commentator entries")

        target_dates = get_target_dates()
        print(f"📅 Target dates: {target_dates}")

        for date_str in target_dates:
            print(f"\n⚽ Processing date: {date_str}")
            navigate_to_date(driver, date_str)
            scrape_date(driver, date_str, commentators)

        print("\n✅ All dates processed successfully.")

    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
