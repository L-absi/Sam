#!/usr/bin/env python3
import json, re, os, time, requests
from datetime import datetime, timedelta
import pytz
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ---------- CONFIG ----------
FIREBASE_URL = os.getenv("FIREBASE_URL")   # مطلوب في البيئة
BASE_MATCH_URL = "https://as-goal.net/match"

# ---------- HELPERS ----------
def get_now_aden():
    return datetime.now(pytz.timezone("Asia/Aden"))

def firebase_get(path):
    url = f"{FIREBASE_URL}/{path}.json"
    try:
        r = requests.get(url, timeout=10)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def firebase_put(path, data):
    url = f"{FIREBASE_URL}/{path}.json"
    try:
        r = requests.put(url, json=data, timeout=20)
        print(f"🔥 Firebase Put [{path}]: {r.status_code}")
    except Exception as e:
        print(f"❌ Firebase Error: {e}")

# ---------- EVENT PARSER FROM VISIBLE TEXT ----------
def parse_events_from_visible_text(visible_text):
    """
    يحلل النص المرئي المستخرج من قسم 'الاحداث' في الصفحة.
    النمط المتوقع (كل حدث مفصول بسطر يحتوي على الدقيقة):
    15'
    0:1
    هدف
    Y. Ibrahim El Hanafi
    صناعة: M. Attia
    ...
    """
    lines = [line.strip() for line in visible_text.splitlines() if line.strip()]
    events = []
    i = 0
    while i < len(lines):
        # الدقيقة تبدأ برقم متبوع بـ ' أو تحتوي على '+'
        if re.match(r"^\d{1,3}'(\+\d+)?$", lines[i]) or re.match(r"^\d{1,3}\+?\d*$", lines[i]):
            minute = lines[i]
            i += 1
            event_data = {"minute": minute, "type": "حدث آخر", "player": "", "extra": "", "raw": []}

            # اجمع السطور التالية حتى بداية الحدث التالي أو نهاية القائمة
            while i < len(lines) and not re.match(r"^\d{1,3}'", lines[i]) and not lines[i].startswith("الشوط"):
                event_data["raw"].append(lines[i])
                i += 1

            full_text = " | ".join(event_data["raw"])
            event_data["raw_text"] = full_text

            # استخراج النتيجة (مثلاً 0:1)
            score_match = re.search(r"(\d+:\d+)", full_text)
            if score_match:
                event_data["score"] = score_match.group(1)

            # تحديد نوع الحدث
            if "هدف" in full_text:
                event_data["type"] = "هدف"
                parts = full_text.split("هدف")[-1].strip()
                player_part = parts.split("صناعة:")[0].strip()
                event_data["player"] = player_part if player_part else ""
            elif "بطاقة صفراء" in full_text:
                event_data["type"] = "بطاقة صفراء"
                player = full_text.split("بطاقة صفراء")[-1].strip()
                event_data["player"] = player
            elif "بطاقة حمراء" in full_text:
                event_data["type"] = "بطاقة حمراء"
                player = full_text.split("بطاقة حمراء")[-1].strip()
                event_data["player"] = player
            elif "تبديل" in full_text:
                event_data["type"] = "استبدال"
                enter = re.search(r"دخول:\s*(.+)", full_text)
                exit_ = re.search(r"خروج:\s*(.+)", full_text)
                if enter and exit_:
                    event_data["player"] = f"خروج: {exit_.group(1)} – دخول: {enter.group(1)}"
            elif "VAR" in full_text:
                event_data["type"] = "VAR"
                event_data["player"] = full_text.replace("VAR", "").strip()
            elif "ركلة ترجيح" in full_text:
                event_data["type"] = "ركلة ترجيح"
                event_data["player"] = ""
            else:
                event_data["type"] = "حدث آخر"

            events.append(event_data)
        else:
            i += 1

    return events

# ---------- MAIN FETCH FUNCTION (FIREBASE VERSION) ----------
def fetch_specific_match():
    match_date = "2026-07-07"
    home = "الارجنتين"
    away = "مصر"
    league_slug = "كأس-العالم"   # يُستخدم في مسار Firebase
    match_id = "b6771feb06522a4042497acda60c89e3"
    url = f"{BASE_MATCH_URL}/{home}-{away}-{match_date}/"

    # إعداد Chrome (يدعم Termux وبيئات أخرى)
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('window-size=1920,1080')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    chromedriver_path = '/data/data/com.termux/files/usr/bin/chromedriver'
    if os.path.exists(chromedriver_path):
        service = Service(chromedriver_path)
    else:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        print(f"🔍 [TEST] Loading: {url}")
        driver.get(url)

        # انتظر تبويب "الاحداث" وانقر عليه إن وُجد
        wait = WebDriverWait(driver, 20)
        try:
            events_tab = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class,'match-tabs')]//span[contains(text(),'الاحداث')]")))
            driver.execute_script("arguments[0].click();", events_tab)
            print("✅ تم النقر على تبويب 'الاحداث'")
            time.sleep(3)
        except Exception as e:
            print(f"⚠️ تعذر النقر على تبويب الأحداث (قد يكون غير ضروري): {e}")

        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # استخراج النتيجة والدقيقة (عدّل المحددات حسب هيكل الصفحة الفعلي)
        score_elem = soup.select_one('.match-scoreboard__scores')
        minute_elem = soup.select_one('.match-scoreboard__status')
        current_score = score_elem.get_text(strip=True) if score_elem else "- -"
        current_minute = minute_elem.get_text(strip=True) if minute_elem else ""

        # استخراج قسم الأحداث
        events_section = soup.find('div', class_='match-event-list') or soup.find('div', id='match-events')
        if events_section:
            visible_text = events_section.get_text(separator='\n', strip=True)
        else:
            visible_text = soup.get_text(separator='\n', strip=True)

        print(f"📋 النص المستخرج من الأحداث:\n{visible_text[:1000]}...")

        events = parse_events_from_visible_text(visible_text)
        print(f"   الأحداث المستخرجة: {len(events)}")

        # مسار التخزين في Firebase
        base_path = f"test_notifications/{match_date}/{league_slug}/{match_id}"
        events_path = f"{base_path}/events"

        # جلب الأحداث المخزنة سابقاً
        stored_events = firebase_get(events_path) or []
        existing_sigs = set()
        for ev in stored_events:
            sig = f"{ev.get('minute','')}|{ev.get('type','')}|{ev.get('player','')}"
            existing_sigs.add(sig)

        new_events = []
        now = get_now_aden()
        for ev in events:
            sig = f"{ev['minute']}|{ev['type']}|{ev['player']}"
            if sig not in existing_sigs:
                scheduled_time = now + timedelta(minutes=5)
                ev['scheduled_send_time'] = scheduled_time.strftime("%Y-%m-%dT%H:%M:%S%z")
                ev['sent'] = False
                new_events.append(ev)
                existing_sigs.add(sig)

        if new_events:
            all_events = stored_events + new_events
            firebase_put(events_path, all_events)
            print(f"   ✅ تمت إضافة {len(new_events)} أحداث جديدة إلى Firebase.")
        else:
            print("   لا توجد أحداث جديدة.")

    finally:
        driver.quit()

if __name__ == "__main__":
    fetch_specific_match()
