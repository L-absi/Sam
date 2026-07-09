#!/usr/bin/env python3
import json, re, hashlib, time, requests
from datetime import datetime
import pytz
import os
from bs4 import BeautifulSoup

# ---------- CONFIG ----------
FIREBASE_URL = os.getenv("FIREBASE_URL")
#"https://laith-5c47d-default-rtdb.firebaseio.com"   # your RTDB URL
FLASK_SEND_URL = "https://lnadeem.pythonanywhere.com/send"    # replace with your actual domain
BASE_MATCH_URL = "https://as-goal.net/match"

# ---------- HELPERS (unchanged) ----------
def get_now_aden():
    return datetime.now(pytz.timezone("Asia/Aden"))

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

def send_notification(title, body):
    payload = {"title": title, "body": body}
    try:
        r = requests.post(FLASK_SEND_URL, json=payload, timeout=10)
        print(f"📢 Notification sent: {title} -> {r.json()}")
    except Exception as e:
        print(f"❌ Notification failed: {e}")

# ---------- PARSING FUNCTIONS (unchanged) ----------
def detect_event_type(icon_src, text):
    # ... نفس الكود السابق ...
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
    # ... نفس الكود السابق ...
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
    # ... نفس الكود السابق ...
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

def build_notification(event, home, away, score):
    # ... نفس الكود السابق ...
    ev_type = event["type"]
    player = event["player"]
    minute = event["minute"]
    raw = event.get("raw", "")

    if ev_type == 'هدف':
        title = "⚽ هدف!"
        body = f"{player} سجل – {score}"
    elif ev_type == 'استراحة':
        title = "⏸️ استراحة"
        body = f"النتيجة {score}"
    elif ev_type == 'نهاية المباراة':
        title = "🏁 نهاية المباراة"
        body = f"انتهت المباراة {score}"
    elif ev_type == 'بداية شوط إضافي':
        title = "⏱️ بداية شوط إضافي"
        body = f"النتيجة {score}"
    elif ev_type == 'بطاقة حمراء':
        title = "🟥 بطاقة حمراء"
        body = f"طرد {player} – {score}"
    elif ev_type == 'بطاقة صفراء':
        title = "🟨 بطاقة صفراء"
        body = f"{player} – {score}"
    elif ev_type == 'استبدال':
        title = "🔄 استبدال"
        body = f"{player} – {score}"
    else:
        title = "📢 حدث في المباراة"
        body = f"{ev_type} - {player} {minute} - {score}"
    return title, body

# ---------- MAIN (MODIFIED) ----------
def process_match(match_date, league_slug, match_id, static_data, live_data):
    home = static_data["home_team"]
    away = static_data["away_team"]
    url = f"{BASE_MATCH_URL}/{home}-{away}-{match_date}/"
    print(f"🔍 Scraping {url}")

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"❌ Failed to fetch {url}: {e}")
        return

    events, current_score, current_minute = parse_events(html, home, away)

    # --- NEW PATHS UNDER notifications/ ---
    base_path = f"notifications/{match_date}/{league_slug}/{match_id}"
    live_path = f"{base_path}/live"
    events_path = f"{base_path}/events"

    # 1. Update live data in the new path
    update_live = {}
    if current_score:
        update_live["score"] = current_score
    if current_minute:
        update_live["minute"] = current_minute
    if "HT" in current_minute or "استراحة" in current_minute:
        update_live["status"] = "استراحة"
    elif "FT" in current_minute or "نهاية" in current_minute:
        update_live["status"] = "انتهت"
    elif current_minute and "'" in current_minute:
        update_live["status"] = "مباشر"
    if update_live:
        firebase_patch(live_path, update_live)

    # 2. Load existing events from new path
    stored_events = firebase_get(events_path) or []
    existing_sigs = set()
    for ev in stored_events:
        sig = f"{ev.get('minute','')}|{ev.get('type','')}|{ev.get('player','')}"
        existing_sigs.add(sig)

    # 3. Filter new events
    new_events = []
    for ev in events:
        sig = f"{ev['minute']}|{ev['type']}|{ev['player']}"
        if sig not in existing_sigs:
            new_events.append(ev)
            existing_sigs.add(sig)

    # 4. Store all events (old + new) in the new path
    if new_events:
        all_events = stored_events + new_events
        firebase_put(events_path, all_events)
        # 5. Send notifications for new events
        for ev in new_events:
            title, body = build_notification(ev, home, away, current_score or (live_data.get('score') if live_data else ""))
            send_notification(title, body)
    else:
        print("   No new events.")

def main():
    today_str = get_now_aden().strftime("%Y-%m-%d")
    print(f"📅 Processing live matches for {today_str}")

    # Still read from matches/ to know which matches are live
    leagues_path = f"matches/{today_str}"
    leagues = firebase_get(leagues_path)
    if not leagues:
        print("No matches found for today.")
        return

    for league_slug, matches_dict in leagues.items():
        if not isinstance(matches_dict, dict):
            continue
        for match_id, match_data in matches_dict.items():
            static_data = match_data.get("static")
            live_data = match_data.get("live", {})
            if not static_data:
                continue
            status = live_data.get("status", "")
            # Process if live or halftime
            if status in ["مباشر", "استراحة"]:
                process_match(today_str, league_slug, match_id, static_data, live_data)

if __name__ == "__main__":
    main()
