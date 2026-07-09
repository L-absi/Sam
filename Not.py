#!/usr/bin/env python3
import json, re, hashlib, time, requests
from datetime import datetime, timedelta
import pytz
import os
from bs4 import BeautifulSoup

# ---------- CONFIG ----------
FIREBASE_URL = os.getenv("FIREBASE_URL")   # يجب تعيينه في البيئة
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

# ---------- PARSING FUNCTIONS ----------
def detect_event_type(icon_src, text):
    if icon_src:
        if 'goal' in icon_src.lower():
            return 'هدف'
        if 'yellow-card' in icon_src.lower():
            return 'بطاقة صفراء'
        if 'red-card' in icon_src.lower():
            return 'بطاقة حمراء'
        if 'substitution' in icon_src.lower():
            return 'استبدال'
    if 'هدف' in text:
        return 'هدف'
    if 'بطاقة صفراء' in text:
        return 'بطاقة صفراء'
    if 'بطاقة حمراء' in text:
        return 'بطاقة حمراء'
    if 'استبدال' in text:
        return 'استبدال'
    if 'استراحة' in text or 'الشوط الأول' in text or 'الشوط الثاني' in text:
        return 'استراحة'
    if 'نهاية المباراة' in text or 'انتهت المباراة' in text:
        return 'نهاية المباراة'
    if 'شوط إضافي' in text:
        return 'بداية شوط إضافي'
    return 'حدث آخر'

def extract_player_from_text(text, event_type):
    if event_type == 'هدف':
        parts = text.split('سجل', 1)
        if len(parts) > 1:
            return parts[1].strip()
        parts = text.split('لـ', 1)
        if len(parts) > 1:
            return parts[1].strip()
    elif event_type in ['بطاقة صفراء', 'بطاقة حمراء']:
        parts = text.split('لـ', 1)
        if len(parts) > 1:
            return parts[1].strip()
    elif event_type == 'استبدال':
        match = re.search(r'خروج (.+?) – دخول (.+)', text)
        if match:
            return f"خروج: {match.group(1)} – دخول: {match.group(2)}"
    return ""

def parse_events(html, home_team, away_team):
    soup = BeautifulSoup(html, 'html.parser')
    score_elem = soup.select_one('.match-score')
    minute_elem = soup.select_one('.match-minute')
    current_score = score_elem.get_text(strip=True) if score_elem else "- -"
    current_minute = minute_elem.get_text(strip=True) if minute_elem else ""

    events = []
    timeline = soup.find('div', class_='match-timeline')
    if not timeline:
        return events, current_score, current_minute

    event_items = timeline.find_all('div', class_='event')
    for item in event_items:
        minute = item.find('div', class_='event-minute')
        text = item.find('div', class_='event-text')
        icon = item.find('img', class_='event-icon')
        minute_str = minute.get_text(strip=True) if minute else ""
        event_text = text.get_text(strip=True) if text else ""
        icon_src = icon['src'] if icon else ""
        event_type = detect_event_type(icon_src, event_text)
        player = extract_player_from_text(event_text, event_type)
        events.append({
            "minute": minute_str,
            "type": event_type,
            "player": player,
            "extra": "",
            "raw": event_text
        })
    return events, current_score, current_minute

# ---------- TEST FETCH FOR SPECIFIC MATCH ----------
def fetch_specific_match():
    # بيانات المباراة المحددة (الأرجنتين - مصر)
    match_date = "2026-07-07"
    home = "الارجنتين"
    away = "مصر"
    league_slug = "كأس-العالم"          # slug المستخدم في قاعدة بياناتك
    match_id = "b6771feb06522a4042497acda60c89e3"  # من الرابط الذي شاركته

    url = f"{BASE_MATCH_URL}/{home}-{away}-{match_date}/"
    print(f"🔍 [TEST] Scraping {url}")

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"❌ Failed to fetch page: {e}")
        return

    events, current_score, current_minute = parse_events(html, home, away)
    print(f"   Found {len(events)} events, score={current_score}, minute={current_minute}")

    # حفظ في مسار test_notifications/{date}/{match_id}/
    base_path = f"test_notifications/{match_date}/{match_id}"
    events_path = f"{base_path}/events"

    # تحميل الأحداث القديمة المخزنة (إن وجدت) لتجنب التكرار
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
            # إضافة وقت إرسال مجدول (بعد 5 دقائق من الآن)
            scheduled_time = now + timedelta(minutes=5)
            ev['scheduled_send_time'] = scheduled_time.strftime("%Y-%m-%dT%H:%M:%S%z")
            ev['sent'] = False          # لم يُرسل بعد
            new_events.append(ev)
            existing_sigs.add(sig)

    if new_events:
        all_events = stored_events + new_events
        firebase_put(events_path, all_events)
        print(f"   ✅ Stored {len(new_events)} new events with future send time.")
    else:
        print("   No new events.")

if __name__ == "__main__":
    fetch_specific_match()
