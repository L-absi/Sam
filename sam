import json
import re
import os
import hashlib
import requests
import time
import pytz
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# -------------------------------------------------------------------
# Configuration & Environment
# -------------------------------------------------------------------
FIREBASE_URL = os.getenv("FIREBASE_URL")
MATCHES_URL = "https://as-goal.net/wsw/"
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

def get_date():
    tz = pytz.timezone("Asia/Aden")
    return datetime.now(tz).strftime("%Y-%m-%d")

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
    return text.lower()

# =========================
# FIREBASE OPERATIONS
# =========================

def firebase_get(path):
    url = f"{FIREBASE_URL}/{path}.json"
    try:
        response = requests.get(url, timeout=10)
        return response.json() if response.status_code == 200 else None
    except: return None

def firebase_patch(path, data):
    url = f"{FIREBASE_URL}/{path}.json"
    try:
        response = requests.patch(url, json=data, timeout=20)
        print(f"🔥 Firebase Sync [{path}]: {response.status_code}")
    except Exception as e:
        print(f"❌ Firebase Error: {e}")

# =========================
# SCRAPING LOGIC
# =========================

def extract_commentators(driver):
    driver.get(COMMENTATORS_URL)
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".mt-league")))
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
    except: return []

def scrape_and_upload():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    try:
        # 1. Get Commentators First
        print("📡 Fetching Commentators...")
        comm_list = extract_commentators(driver)
        
        # 2. Get Today's Matches (No navigation to yesterday)
        print(f"📡 Fetching Matches from: {MATCHES_URL}")
        driver.get(MATCHES_URL)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".anwp-fl-game")))
        
        # Scroll to ensure all matches load
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        date_str = get_date()
        
        league_blocks = soup.find_all('div', class_='anwp-fl-block-header')
        
        for header in league_blocks:
            league_name = header.find('a').get_text(strip=True) if header.find('a') else 'Unknown'
            league_logo = header.find('img')['src'] if header.find('img') else ''
            slug = league_slug(league_name)
            
            # Update League Info
            firebase_patch(f"leagues/{date_str}/{slug}", {"name": league_name, "logo": league_logo})

            next_elem = header.find_next_sibling()
            while next_elem and 'anwp-fl-block-header' not in next_elem.get('class', []):
                if 'anwp-fl-game' in next_elem.get('class', []):
                    # Basic Info
                    home = next_elem.find('div', class_='match-slim__team-home-title').get_text(strip=True)
                    away = next_elem.find('div', class_='match-slim__team-away-title').get_text(strip=True)
                    h_logo = next_elem.find('img', class_='match-slim__team-home-logo')['src'] if next_elem.find('img', class_='match-slim__team-home-logo') else ''
                    a_logo = next_elem.find('img', class_='match-slim__team-away-logo')['src'] if next_elem.find('img', class_='match-slim__team-away-logo') else ''
                    m_time = next_elem.find('span', class_='match-slim__time').get_text(strip=True) if next_elem.find('span', class_='match-slim__time') else ''
                    
                    # Live Stats
                    h_score = next_elem.find('span', class_='match-slim__scores-home').get_text(strip=True) if next_elem.find('span', class_='match-slim__scores-home') else '-'
                    a_score = next_elem.find('span', class_='match-slim__scores-away').get_text(strip=True) if next_elem.find('span', class_='match-slim__scores-away') else '-'
                    
                    # Match Commentator & Channel Matching
                    match_comm = "غير مدرج"
                    match_chan = "غير مدرج"
                    for c in comm_list:
                        if normalize_text(home) == normalize_text(c['home']):
                            match_comm = c['commentator']
                            match_chan = CHANNEL_MAP.get(c['channel'], c['channel'])
                            break

                    match_id = generate_match_id(home, away, league_name)
                    
                    # Structure Data as requested
                    static_data = {
                        "league": league_name,
                        "league_logo": league_logo,
                        "home_team": home,
                        "home_logo": h_logo,
                        "away_team": away,
                        "away_logo": a_logo,
                        "channel": [match_chan],
                        "commentator": match_comm,
                        "time": m_time
                    }
                    
                    live_data = {
                        "status": "مباشر" if h_score != "-" else "لم تبدأ",
                        "score": f"{h_score} - {a_score}",
                        "minute": "" # المواقع الحالية قد لا توفر الدقيقة بسهولة في هذا التصميم
                    }

                    # Firebase Sync
                    match_path = f"matches/{date_str}/{slug}/{match_id}"
                    
                    # Only update static if not exists
                    if not firebase_get(f"{match_path}/static"):
                        firebase_patch(f"{match_path}/static", static_data)
                    
                    # Always check live data update
                    old_live = firebase_get(f"{match_path}/live")
                    if old_live != live_data:
                        firebase_patch(f"{match_path}/live", live_data)

                next_elem = next_elem.find_next_sibling()

    finally:
        driver.quit()
        print("✅ Process Completed")

if __name__ == "__main__":
    scrape_and_upload()
