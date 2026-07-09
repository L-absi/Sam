#!/usr/bin/env python3
import json, re, os, hashlib, requests, time
from datetime import datetime, timedelta
import pytz
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
FLASK_SEND_URL = os.getenv("FLASK_SEND_URL", "https://lnadeem.pythonanywhere.com/send")
BASE_MATCHES_URL = "https://as-goal.net/wsw/"
BASE_MATCH_URL = "https://as-goal.net/match"
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
        print(f"🔥 Firebase Patch [{path}]: {r.status_code}")
    except Exception as e:
        print(f"❌ Firebase Error: {e}")

def firebase_put(path, data):
    url = f"{FIREBASE_URL}/{path}.json"
    try:
        r = requests.put(url, json=data, timeout=20)
        print(f"🔥 Firebase Put [{path}]: {r.status_code}")
    except Exception as e:
        print(f"❌ Firebase Error: {e}")

# =========================
# NOTIFICATION HELPERS
# =========================
def send_notification(title, body):
    payload = {"title": title, "body": body}
    try:
        r = requests.post(FLASK_SEND_URL, json=payload, timeout=10)
        print(f"📢 Sent: {title} -> {r.status_code}")
    except Exception as e:
        print(f"❌ Notification failed: {e}")

# =========================
# LIVE UPDATE PROTECTION
# =========================
def should_update_live(existing_live, new_live_data):
    """
    يقرر ما إذا كنا سنستبدل القيم الحالية بالقيم الجديدة.
    نحمي من فقدان البيانات المؤقت (مثلاً النتيجة تختفي للحظات).
    """
    if not existing_live:
        return True  # لا توجد بيانات سابقة، نكتب الجديد

    now = get_now_aden()
    last_valid_str = existing_live.get("last_valid_update")
    if last_valid_str:
        try:
            last_valid = datetime.strptime(last_valid_str, "%Y-%m-%dT%H:%M:%S%z")
            if (now - last_valid).total_seconds() < 180:  # أقل من 3 دقائق
                # لدينا بيانات سابقة حديثة، نقارن القيم الجديدة بالافتراضية
                new_score = new_live_data.get("score", "- -")
                new_status = new_live_data.get("status", "لم تبدأ")
                # إذا كانت القيم الجديدة تشير إلى "لم تبدأ" أو نتيجة فارغة، نرفض التحديث
                if new_status == "لم تبدأ" or new_score in ("- -", "? - ?", ""):
                    return False  # لا نحدث
        except:
            pass
    return True

# =========================
# COMMENTATORS STORAGE
# =========================
def save_commentators_to_firebase(date_str, commentators_list):
    firebase_patch(f"commentators/{date_str}", commentators_list)

def get_commentators_from_firebase(date_str):
    data = firebase_get(f"commentators/{date_str}")
    if data and isinstance(data, list):
        return data
    return []

# =========================
# SCRAPING: MATCH LIST
# =========================
def extract_commentators(driver):
    driver.get(COMMENTATORS_URL)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".mt-match"))
        )
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        commentators = []
        matches = soup.find_all('div', class_='mt-match')
        for match in matches:
            teams = match.find_all('div', class_='mt-team')
            if len(teams) >= 2:
                league_elem = match.find_parent('div', class_='mt-league')
                league_name = league_elem.find('h3').get_text(strip=True) if league_elem and league_elem.find('h3') else ''
                commentators.append({
                    'league': league_name,
                    'home': teams[0].get_text(strip=True),
                    'away': teams[1].get_text(strip=True),
                    'commentator': match.find('div', class_='mt-commentator').get_text(strip=True) if match.find('div', class_='mt-commentator') else '',
                    'channel': match.find('div', class_='mt-channel').get_text(strip=True) if match.find('div', class_='mt-channel') else ''
                })
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
    btn_selector = ".anwp-fl-calendar-slider__swiper-button-prev" if offset < 0 else ".anwp-fl-calendar-slider__swiper-button-next"
    clicks = abs(offset)
    print(f"   🔘 Need to click {btn_selector} {clicks} time(s)")
    for i in range(clicks):
        try:
            btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, btn_selector)))
            btn.click()
            time.sleep(2.5)
        except Exception as e:
            print(f"   ⚠️ Failed to click {btn_selector}: {e}")
            break
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".anwp-fl-game")))
        print(f"   ✅ Successfully navigated to {target_date}")
    except:
        print(f"   ❌ Could not confirm matches loaded for {target_date}")

def scrape_date(driver, date_str, commentators_list):
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    league_blocks = soup.find_all('div', class_='anwp-fl-block-header')
    if not league_blocks:
        print(f"   ℹ️ No leagues found for {date_str}")
        return []

    now_aden_str = get_now_aden().strftime("%Y-%m-%d")
    live_matches = []  # لتجميع المباريات الحية التي تحتاج إلى تفاصيل

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

                # ---------- استخراج الحالة والدقيقة ----------
                live_block = next_elem.find('div', class_='match-list__live-block')
                status = "لم تبدأ"
                minute = ""
                if live_block:
                    live_status_elem = live_block.find('span', class_='anwp-fl-game__live-status')
                    if live_status_elem:
                        status = live_status_elem.get_text(strip=True)
                    else:
                        status = "مباشر"
                    live_time_elem = live_block.find('span', class_='anwp-fl-game__live-time')
                    if live_time_elem:
                        minute = live_time_elem.get_text(strip=True)
                else:
                    if h_score != '-' and a_score != '-':
                        status = "انتهت"
                        minute = "FT"
                    else:
                        status = "لم تبدأ"
                        minute = ""

                # المعلق والقناة
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

                # static data
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

                # live data
                new_live = {
                    "status": status,
                    "score": f"{h_score} - {a_score}",
                    "minute": minute
                }

                existing_live = firebase_get(f"{match_path}/live")

                # --- حماية المعلق والقناة ---
                if match_comm != "غير مدرج":
                    new_live["commentator"] = match_comm
                else:
                    old_comm = existing_live.get("commentator") if existing_live else "غير مدرج"
                    if old_comm and old_comm != "غير مدرج":
                        new_live["commentator"] = old_comm
                    else:
                        new_live["commentator"] = "غير مدرج"

                if match_chan != "غير مدرج":
                    new_live["channel"] = [match_chan]
                else:
                    old_chan = existing_live.get("channel") if existing_live else ["غير مدرج"]
                    if old_chan and old_chan != ["غير مدرج"]:
                        new_live["channel"] = old_chan
                    else:
                        new_live["channel"] = ["غير مدرج"]

                # --- حماية من القيم المؤقتة ---
                allow_update = should_update_live(existing_live, new_live)
                if allow_update:
                    # تحديث الطابع الزمني لآخر تحديث صحيح
                    new_live["last_valid_update"] = get_now_aden().strftime("%Y-%m-%dT%H:%M:%S%z")
                    firebase_patch(f"{match_path}/live", new_live)
                else:
                    print(f"   ⏳ تم تجاهل تحديث افتراضي مؤقت لـ {home} vs {away}")

                # إذا كانت المباراة مباشرة أو استراحة، أضفها إلى قائمة المعالجة
                if status in ["مباشر", "استراحة"]:
                    live_matches.append({
                        "date": date_str,
                        "slug": slug,
                        "match_id": match_id,
                        "home": home,
                        "away": away
                    })

            next_elem = next_elem.find_next_sibling()

    return live_matches

# =========================
# SCRAPING: MATCH DETAILS & EVENTS
# =========================
def parse_events_from_html(html, home_team, away_team):
    soup = BeautifulSoup(html, 'html.parser')
    events = []
    event_rows = soup.find_all('div', class_='match-commentary__row')
    for row in event_rows:
        team = None
        if row.find('div', class_='match-commentary__block--home'):
            team = home_team
        elif row.find('div', class_='match-commentary__block--away'):
            team = away_team

        classes = row.get('class', [])
        event_type_class = ""
        for c in classes:
            if c.startswith('match-commentary__event--'):
                event_type_class = c.replace('match-commentary__event--', '')
                break

        minute_elem = row.find('span', class_='match-commentary__minute')
        minute = minute_elem.get_text(strip=True) if minute_elem else ""

        scores_elem = row.find('span', class_='match-commentary__scores')
        score = scores_elem.get_text(strip=True) if scores_elem else ""

        event_name_elem = row.find('span', class_='match-commentary__event-name')
        event_name = event_name_elem.get_text(strip=True) if event_name_elem else event_type_class

        sub_header = row.find('div', class_='match-commentary__block-sub-header')
        player = ""
        assist = ""
        if sub_header:
            for content in sub_header.contents:
                if isinstance(content, str) and content.strip():
                    if 'صناعة' not in content and 'دخول' not in content and 'خروج' not in content:
                        player = content.strip()
                        break
            if event_type_class == 'substitute' or event_name == 'تبديل':
                enter_match = re.search(r'دخول:\s*(.+?)(?=\s*(خروج:|$))', sub_header.get_text())
                exit_match = re.search(r'خروج:\s*(.+?)$', sub_header.get_text())
                enter_player = enter_match.group(1).strip() if enter_match else ""
                exit_player = exit_match.group(1).strip() if exit_match else ""
                if enter_player and exit_player:
                    player = f"{exit_player} ↔ {enter_player}"
                else:
                    player = sub_header.get_text(strip=True)
            if event_type_class == 'goal' or event_name == 'هدف':
                assist_elems = sub_header.find_all('span', class_='match-commentary__meta')
                for a in assist_elems:
                    if 'صناعة' in a.get_text():
                        next_text = a.find_next(string=True)
                        if next_text:
                            assist = next_text.strip()
                            break

        extra = ""
        extra_text_elem = row.find('div', class_='match-commentary__block-text')
        if extra_text_elem:
            extra = extra_text_elem.get_text(strip=True)

        events.append({
            "minute": minute,
            "type": event_name if event_name else event_type_class,
            "player": player,
            "score": score,
            "team": team,
            "extra": extra,
            "assist": assist,
            "event_class": event_type_class
        })
    return events

def build_notification(event, home, away):
    t = event.get("type", "")
    player = event.get("player", "")
    minute = event.get("minute", "")
    score = event.get("score", "")
    team = event.get("team", "")
    assist = event.get("assist", "")
    extra = event.get("extra", "")

    team_display = f"منتخب {team}" if team else ""

    if "هدف" in t:
        title = f"⚽ هدف لـ{team_display}" if team_display else "⚽ هدف!"
        body = f"سجل {player} في الدقيقة {minute}"
        if assist:
            body += f" (صناعة: {assist})"
        if score:
            body += f" – النتيجة {score}"
    elif "بطاقة صفراء" in t:
        title = f"🟨 بطاقة صفراء لـ{team_display}" if team_display else "🟨 بطاقة صفراء"
        body = f"{player} في الدقيقة {minute}"
        if extra:
            body += f" ({extra})"
    elif "بطاقة حمراء" in t:
        title = f"🟥 بطاقة حمراء لـ{team_display}" if team_display else "🟥 بطاقة حمراء"
        body = f"{player} في الدقيقة {minute}"
        if extra:
            body += f" ({extra})"
    elif "تبديل" in t:
        title = f"🔄 تبديل لـ{team_display}" if team_display else "🔄 تبديل"
        body = f"{player} في الدقيقة {minute}"
    elif "VAR" in t:
        title = f"📺 VAR - {team_display}" if team_display else "📺 VAR"
        body = f"{player} {extra}"
    else:
        title = "📢 حدث"
        body = f"{t} - {player} {minute} - {score}"

    return title, body

def process_live_match(driver, match_info):
    """يفتح صفحة تفاصيل المباراة ويستخرج الأحداث ويرسل الإشعارات."""
    date_str = match_info["date"]
    slug = match_info["slug"]
    match_id = match_info["match_id"]
    home = match_info["home"]
    away = match_info["away"]

    url = f"{BASE_MATCH_URL}/{home}-{away}-{date_str}/"
    print(f"🔍 Fetching events for {home} vs {away}...")
    try:
        driver.get(url)
        # انتظر تبويب الأحداث
        try:
            events_tab = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@class,'match-tabs')]//span[contains(text(),'الاحداث')]"))
            )
            driver.execute_script("arguments[0].click();", events_tab)
            time.sleep(3)
        except:
            pass

        html = driver.page_source
        events = parse_events_from_html(html, home, away)

        # مسار التخزين الجديد للإشعارات
        events_path = f"notifications/{date_str}/{slug}/{match_id}/events"
        stored_events = firebase_get(events_path) or []

        existing_sigs = set()
        for ev in stored_events:
            sig = f"{ev.get('minute','')}|{ev.get('type','')}|{ev.get('player','')}"
            existing_sigs.add(sig)

        new_events = []
        for ev in events:
            sig = f"{ev['minute']}|{ev['type']}|{ev['player']}"
            if sig not in existing_sigs:
                new_events.append(ev)
                existing_sigs.add(sig)

        if new_events:
            # حفظ الكل
            all_events = stored_events + new_events
            firebase_put(events_path, all_events)
            # إرسال إشعارات
            for ev in new_events:
                title, body = build_notification(ev, home, away)
                send_notification(title, body)
            print(f"   ✅ {len(new_events)} أحداث جديدة تمت معالجتها.")
        else:
            print("   لا توجد أحداث جديدة.")
    except Exception as e:
        print(f"   ❌ خطأ أثناء معالجة {home} vs {away}: {e}")

# =========================
# MAIN
# =========================
def main():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('window-size=1920,1080')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        target_dates = get_target_dates()
        print(f"📅 Target dates: {target_dates}")

        today_str = get_now_aden().strftime("%Y-%m-%d")
        print(f"📡 Fetching today's commentators...")
        commentators_today = extract_commentators(driver)
        if commentators_today:
            print(f"   Found {len(commentators_today)} entries – saving to Firebase")
            save_commentators_to_firebase(today_str, commentators_today)
        else:
            print("   No commentators found for today, will rely on stored data.")

        # قائمة لتجميع المباريات الحية
        all_live_matches = []

        for date_str in target_dates:
            print(f"\n⚽ Processing date: {date_str}")
            navigate_to_date(driver, date_str)

            if date_str == today_str:
                commentators = commentators_today
            else:
                commentators = get_commentators_from_firebase(date_str)
                if not commentators:
                    print(f"   ⚠️ No stored commentators for {date_str}, trying live page (may fail)")
                    commentators = extract_commentators(driver)

            live_matches = scrape_date(driver, date_str, commentators)
            all_live_matches.extend(live_matches)

        # معالجة أحداث المباريات الحية
        print(f"\n📡 معالجة أحداث {len(all_live_matches)} مباراة حية...")
        for match in all_live_matches:
            process_live_match(driver, match)

        print("\n✅ All dates and events processed successfully.")

    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
