#!/usr/bin/env python3
import requests
from datetime import datetime
import pytz
import os

# ---------- CONFIG ----------
FIREBASE_URL = os.getenv("FIREBASE_URL")   # نفس المتغير المستخدم في السكربت الأول
FLASK_SEND_URL = "https://lnadeem.pythonanywhere.com/send"

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

def firebase_patch(path, data):
    url = f"{FIREBASE_URL}/{path}.json"
    try:
        r = requests.patch(url, json=data, timeout=20)
        print(f"🔥 Firebase Patch [{path}]: {r.status_code}")
    except Exception as e:
        print(f"❌ Firebase Error: {e}")

def send_notification(title, body):
    payload = {"title": title, "body": body}
    try:
        r = requests.post(FLASK_SEND_URL, json=payload, timeout=10)
        print(f"📢 Sent: {title} -> {r.status_code}")
    except Exception as e:
        print(f"❌ Notification failed: {e}")

# ---------- NOTIFICATION BUILDER (مطابقة للسكربت الأول) ----------
def build_notification(event):
    ev_type = event["type"]
    player = event["player"]
    minute = event["minute"]
    score = event.get("score", "")   # يمكنك إضافتها يدويًا إذا أردت

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

# ---------- MAIN ----------
def send_scheduled_events():
    # حدد المباراة التي نعمل عليها (نفس بيانات الاختبار)
    match_date = "2026-07-07"
    match_id = "b6771feb06522a4042497acda60c89e3"
    league_slug = "كأس-العالم"
    #events_path = f"test_notifications/{match_date}/{match_id}/events"
    events_path = f"test_notifications/{match_date}/{league_slug}/{match_id}/events"

    print(f"🔍 Checking scheduled events in {events_path}")
    events = firebase_get(events_path)
    if not events:
        print("No events found.")
        return

    now_aden = get_now_aden()
    updates = {}

    for idx, ev in enumerate(events):
        # تجاهل إذا أُرسل سابقاً
        if ev.get("sent", False):
            continue

        scheduled_str = ev.get("scheduled_send_time")
        if not scheduled_str:
            continue

        # تحويل النص إلى كائن وقت (بافتراض التنسيق "%Y-%m-%dT%H:%M:%S%z")
        try:
            scheduled_dt = datetime.strptime(scheduled_str, "%Y-%m-%dT%H:%M:%S%z")
        except:
            # في حال تنسيق مختلف، تجاهل
            print(f"⚠️ Invalid date format for event index {idx}: {scheduled_str}")
            continue

        # إذا حان وقت الإرسال (الوقت المجدول <= الآن)
        if scheduled_dt <= now_aden:
            title, body = build_notification(ev)
            send_notification(title, body)
            updates[f"{idx}/sent"] = True

    if updates:
        firebase_patch(events_path, updates)
        print(f"✅ Marked {len(updates)} events as sent.")
    else:
        print("No pending events to send at this time.")

if __name__ == "__main__":
    send_scheduled_events()
