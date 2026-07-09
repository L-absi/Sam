#!/usr/bin/env python3
import requests
from datetime import datetime
import pytz
import os

# ---------- CONFIG ----------
FIREBASE_URL = os.getenv("FIREBASE_URL")
if not FIREBASE_URL:
    print("❌ FIREBASE_URL غير مضبوط. استخدم export FIREBASE_URL='...'")
    exit(1)

FLASK_SEND_URL = "https://lnadeem.pythonanywhere.com/send"

# ---------- HELPERS ----------
def get_now_aden():
    return datetime.now(pytz.timezone("Asia/Aden"))

def firebase_get(path):
    url = f"{FIREBASE_URL}/{path}.json"
    print(f"   📡 GET {url}")
    try:
        r = requests.get(url, timeout=10)
        print(f"   🔁 Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            if data is None:
                print("   ⚠️ البيانات فارغة (null)")
            return data
        else:
            print(f"   ❌ استجابة غير 200: {r.text[:200]}")
            return None
    except Exception as e:
        print(f"   ❌ استثناء: {e}")
        return None

def firebase_patch(path, data):
    url = f"{FIREBASE_URL}/{path}.json"
    try:
        r = requests.patch(url, json=data, timeout=20)
        print(f"🔥 Firebase Patch [{path}]: {r.status_code}")
        if r.status_code != 200:
            print(f"   Response: {r.text[:200]}")
    except Exception as e:
        print(f"❌ Firebase Error: {e}")

def send_notification(title, body):
    payload = {"title": title, "body": body}
    try:
        r = requests.post(FLASK_SEND_URL, json=payload, timeout=10)
        print(f"📢 Sent: {title} -> {r.status_code}")
        if r.status_code != 200:
            print(f"   Response: {r.text[:200]}")
    except Exception as e:
        print(f"❌ Notification failed: {e}")

# ---------- NOTIFICATION BUILDER ----------
def build_notification(event):
    ev_type = event.get("type", "حدث آخر")
    player = event.get("player", "")
    minute = event.get("minute", "")
    score = event.get("score", "")

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
    match_date = "2026-07-07"
    match_id = "b6771feb06522a4042497acda60c89e3"
    league_slug = "كأس-العالم"
    events_path = f"test_notifications/{match_date}/{league_slug}/{match_id}/events"

    print(f"🔍 Checking scheduled events in {events_path}")
    events = firebase_get(events_path)

    # إذا كانت البيانات داخل كائن وليس قائمة مباشرة
    if events is None:
        print("❌ فشل في جلب البيانات، تحقق من FIREBASE_URL والمسار.")
        return

    if isinstance(events, dict):
        # ربما البيانات ملفوفة بمفتاح إضافي
        print("   ⚠️ البيانات وردت ككائن وليست قائمة، محاولة استخراج القائمة...")
        # جرب المفتاح 'events' إن وجد
        if 'events' in events:
            events = events['events']
        else:
            # ربما كل القيم هي الأحداث
            events = list(events.values())

    if not isinstance(events, list):
        print(f"❌ تنسيق غير متوقع: {type(events)}")
        return

    if len(events) == 0:
        print("   لا توجد أحداث مخزنة.")
        return

    print(f"   ✅ تم جلب {len(events)} حدثًا.")

    now_aden = get_now_aden()
    updates = {}

    for idx, ev in enumerate(events):
        if ev.get("sent", False):
            continue

        scheduled_str = ev.get("scheduled_send_time")
        if not scheduled_str:
            continue

        try:
            # تنسيق الوقت الذي استخدمناه: "2026-07-09T05:00:26+0300"
            scheduled_dt = datetime.strptime(scheduled_str, "%Y-%m-%dT%H:%M:%S%z")
        except Exception as e:
            print(f"⚠️ تنسيق وقت خاطئ للحدث {idx}: {scheduled_str} | {e}")
            continue

        # للتجربة: تجاهل شرط الوقت وأرسل كل الأحداث غير المرسلة (مؤقتًا)
        if scheduled_dt <= now_aden:   # أو استخدم True للتجربة
            title, body = build_notification(ev)
            send_notification(title, body)
            updates[f"{idx}/sent"] = True
            # لتجنب إرسال مئات الإشعارات دفعة واحدة، أضف تأخيرًا بسيطًا
            # time.sleep(1)

    if updates:
        firebase_patch(events_path, updates)
        print(f"✅ تم تعليم {len(updates)} حدثًا كـ 'مرسل'.")
    else:
        print("   لا توجد أحداث مستحقة للإرسال (أو أن وقتها لم يحن بعد).")

if __name__ == "__main__":
    send_scheduled_events()
