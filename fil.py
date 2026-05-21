import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime
import hashlib
import re
import re
from difflib import SequenceMatcher

BASE_URL = os.getenv("BASE_URL")


def normalize_team_name(name):
    """تطبيع اسم الفريق: إزالة '| تحت 17' و 'تحت 17' وأي شيء مشابه"""
    if not name:
        return ""
    # إزالة اللواحق مثل "| تحت 17" أو "تحت 17"
    name = re.sub(r'\s*[|]\s*تحت\s*17\s*', '', name)
    name = re.sub(r'\s*تحت\s*17\s*', '', name)
    # إزالة الكلمات الزائدة
    name = re.sub(r'\s*-\s*', ' ', name)
    return name.strip()

def get_league_key(league_name):
    """
    تحويل اسم البطولة إلى مفتاح موحد للمقارنة.
    يستخدم قاموس مرادفات وتنظيف النص.
    """
    if not league_name:
        return ""
    
    # تنظيف اسم الدوري من الجولة
    cleaned = re.sub(r'\s*[-–]\s*الجولة\s*\d+', '', league_name).strip()
    cleaned = re.sub(r'\s*[-–]\s*$', '', cleaned)
    
    # قاموس المرادفات
    synonyms = {
        "بطولة أمم إفريقيا | تحت 17": "africa_u17",
        "بطولة إفريقيا 17 سنة": "africa_u17",
        "الدوري المصري": "egypt",
        "الدوري السعودي": "saudi",
        "الدوري السعودي للمحترفين": "saudi",
        "الدوري الأوروبي": "europa",
        "نهائي الدوري الأوروبي": "europa",
        "كأس الليبرتادوريس": "libertadores",
        "كوبا سود أميريكانا": "sudamericana",
        "دوري نجوم العراق": "iraq",
        "كأس تونس": "tunisia_cup",
        "الرابطة الجزائرية المحترفة لكرة القدم": "algeria",
    }
    
    for key, value in synonyms.items():
        if key in cleaned or cleaned in key:
            return value
    
    # إذا لم يجد، نعيد الاسم بعد تنظيفه
    return cleaned

def normalize_time_to_hour(time_str):
    """تحويل الوقت إلى رقم الساعة (0-23)"""
    if not time_str:
        return None
    
    # صيغة FilGoal: "20-05-2026 - 20:00"
    match = re.search(r'(\d{2})-(\d{2})-(\d{4})\s*-\s*(\d{2}):(\d{2})', time_str)
    if match:
        return int(match.group(4))
    
    # صيغة AsGoal: "7:00 م" أو "10:00 ص"
    match = re.search(r'(\d{1,2}):(\d{2})\s*(ص|م)', time_str)
    if match:
        hour = int(match.group(1))
        if match.group(3) == 'م' and hour != 12:
            hour += 12
        elif match.group(3) == 'ص' and hour == 12:
            hour = 0
        return hour
    
    return None

def are_teams_similar(name1, name2, threshold=0.7):
    """
    مقارنة اسمي فريق باستخدام التشابه النصي (fuzzy matching).
    تستخدم عندما لا يتطابق الاسم بشكل تام.
    """
    if not name1 or not name2:
        return False
    name1 = normalize_team_name(name1)
    name2 = normalize_team_name(name2)
    if name1 == name2:
        return True
    # استخدام SequenceMatcher لحساب نسبة التشابه
    similarity = SequenceMatcher(None, name1, name2).ratio()
    return similarity >= threshold

def merge_matches_data(filgoal_data, asgoal_data):
    """
    دمج بيانات المباريات من المصدرين مع معالجة اختلافات الأسماء.
    """
    if not filgoal_data or not asgoal_data:
        print("⚠️ أحد المصدرين فارغ، لا يمكن الدمج.")
        return filgoal_data

    date_str = list(filgoal_data["matches"].keys())[0]
    merged_data = filgoal_data

    # بناء قاموس AsGoal بمفاتيح محسنة
    asgoal_dict = {}
    asgoal_matches = asgoal_data["matches"].get(date_str, {})
    
    for league_name_as, matches in asgoal_matches.items():
        league_key_as = get_league_key(league_name_as)
        for match_info in matches.values():
            hour = normalize_time_to_hour(match_info.get("time", ""))
            if hour is None:
                continue
            
            home_norm = normalize_team_name(match_info.get("home_team", ""))
            away_norm = normalize_team_name(match_info.get("away_team", ""))
            
            if not home_norm or not away_norm:
                continue
            
            # المفتاح الأساسي: (الفريقين، الدوري، الساعة)
            key = (home_norm, away_norm, league_key_as, hour)
            asgoal_dict[key] = {
                "commentator": match_info.get("commentator", "غير معلن"),
                "channel": match_info.get("channel", ["غير معلن"]),
                "original_home": match_info.get("home_team", ""),
                "original_away": match_info.get("away_team", "")
            }

    # تحديث مباريات FilGoal
    matched_count = 0
    for league_name_fg, matches in merged_data["matches"][date_str].items():
        league_key_fg = get_league_key(league_name_fg)
        for match_info in matches.values():
            hour = normalize_time_to_hour(match_info.get("time", ""))
            if hour is None:
                continue
            
            home_norm = normalize_team_name(match_info.get("home_team", ""))
            away_norm = normalize_team_name(match_info.get("away_team", ""))
            
            # البحث عن تطابق تام أولاً
            key = (home_norm, away_norm, league_key_fg, hour)
            if key in asgoal_dict:
                match_info["commentator"] = asgoal_dict[key]["commentator"]
                match_info["channel"] = asgoal_dict[key]["channel"]
                matched_count += 1
                print(f"✅ تم دمج (تطابق تام): {match_info['home_team']} 🆚 {match_info['away_team']}")
                continue
            
            # إذا لم يجد تطابق تام، نحاول مطابقة مرنة مع عكس الترتيب (في حال كان الفريقان معكوسين)
            key_reversed = (away_norm, home_norm, league_key_fg, hour)
            if key_reversed in asgoal_dict:
                match_info["commentator"] = asgoal_dict[key_reversed]["commentator"]
                match_info["channel"] = asgoal_dict[key_reversed]["channel"]
                matched_count += 1
                print(f"✅ تم دمج (معكوس): {match_info['home_team']} 🆚 {match_info['away_team']}")
                continue
            
            # إذا لم يجد، نبحث في جميع مفاتيح AsGoal باستخدام التشابه النصي (أبطأ لكن دقيق)
            found = False
            for (h, a, lk, hh), val in asgoal_dict.items():
                if lk == league_key_fg and hh == hour:
                    if are_teams_similar(home_norm, h) and are_teams_similar(away_norm, a):
                        match_info["commentator"] = val["commentator"]
                        match_info["channel"] = val["channel"]
                        matched_count += 1
                        print(f"✅ تم دمج (تشابه نصي): {match_info['home_team']} 🆚 {match_info['away_team']}")
                        found = True
                        break
            if not found:
                print(f"⚠️ لم يتم العثور على تطابق لـ: {match_info['home_team']} 🆚 {match_info['away_team']}")

    print(f"\n📊 تم دمج {matched_count} مباراة من أصل {sum(len(m) for m in merged_data['matches'][date_str].values())}")
    return merged_data


def fix_image_url(url):
    """تحويل الرابط إلى صيغة كاملة صالحة لـ Glide"""
    if not url:
        return ""
    if url.startswith('//'):
        return f"https:{url}"
    if not url.startswith('http'):
        return f"https://{url}"
    return url
    



# ================== إعدادات المسارات ==================

# ================== المتغيرات العامة ==================


# ================== قاموس المرادفات والاستثناءات ==================
# قاموس لتصحيح أسماء البطولات غير الموجودة في LeagueData


# قاموس أسماء الدول العربية إلى الإنجليزية (لمنع الترجمة الخاطئة)


# ================== دوال التحميل ==================


# ================== دوال البحث عن الشعارات ==================


# ================== دوال التاريخ والرفع ==================
def get_today_date():
    return datetime.now().strftime("%Y-%m-%d")

def push_to_firebase_structured(database_structure):
    today_date = get_today_date()
    leagues_data = database_structure.get("leagues", {}).get(today_date, {})
    matches_data = database_structure.get("matches", {}).get(today_date, {})
    
    for league_name, league_info in leagues_data.items():
        league_url = f"{BASE_URL}/leagues/{today_date}/{league_name}.json"
        requests.put(league_url, json=league_info)
    
    for league_name, matches in matches_data.items():
        for match_id, match_details in matches.items():
            match_url = f"{BASE_URL}/matches/{today_date}/{league_name}/{match_id}.json"
            requests.put(match_url, json=match_details)
    
    print(f"✅ تم تحديث بيانات Firebase بتاريخ {today_date}")

# ================== دالة السحب الرئيسية ==================
def scrape_to_database_structure(urlcomm, output_filename="today_matches_as.json"):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
    
    try:
        print("🌐 جاري الاتصال بالموقع وجلب المباريات الحية...")
        response = requests.get(urlcomm, headers=headers)
        response.raise_for_status()
        response.encoding = 'utf-8'
    except Exception as e:
        print(f"❌ خطأ في الاتصال بالموقع: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    today_date = get_today_date()
    
    database_structure = {
        "leagues": {today_date: {}},
        "matches": {today_date: {}}
    }

    # 🔍 البحث عن جميع عناصر المباريات (كل مباراة في div يحمل كلاساً معيناً)
    # في as-goal.net، المباريات تكون داخل div يحمل class="anwp-match" أو "mt-match"
    match_blocks = soup.find_all('div', class_=lambda x: x and ('anwp-match' in x or 'match-row' in x or 'mt-match' in x))
    print(f"⚡ تم العثور على {len(match_blocks)} مباراة. جاري البدء بمعالجة البيانات...\n")
    
    for block in match_blocks:
        try:
            # اسم الدوري: نبحث عن أقرب عنصر h2 أو h3 يحمل class يحوي "league"
            league_elem = block.find_previous(['h2', 'h3', 'div'], class_=lambda x: x and ('league' in x or 'mt-league' in x))
            league_name = league_elem.text.strip() if league_elem else "Unknown League"
            league_name_clean = " ".join(league_name.split())
            
            # إزالة تفاصيل الجولة من اسم الدوري إذا وجدت (اختياري)
            league_name_clean = re.sub(r'[-–]\s*الجولة\s*\d+', '', league_name_clean).strip()
            
            if league_name_clean not in database_structure["leagues"][today_date]:
                print(f"🏆 جاري معالجة بطولة: {league_name_clean}")
                database_structure["leagues"][today_date][league_name_clean] = {
                    "logo": "",
                    "name": league_name_clean
                }
            
            if league_name_clean not in database_structure["matches"][today_date]:
                database_structure["matches"][today_date][league_name_clean] = {}
            
            # 🔍 استخراج الفريقين - المحددات الصحيحة لموقع as-goal.net
            # الفريق المضيف
            home_elem = block.select_one('.anwp-match__team-home, .mt-team-home, .home-team')
            away_elem = block.select_one('.anwp-match__team-away, .mt-team-away, .away-team')
            
            # إذا لم يجد باستخدام هذه المحددات، جرب البحث العام
            if not home_elem or not away_elem:
                team_elements = block.select('.anwp-match__team, .mt-team, .team-name')
                if len(team_elements) >= 2:
                    home_elem = team_elements[0]
                    away_elem = team_elements[1]
            
            if not home_elem or not away_elem:
                continue
                
            team_home = home_elem.text.strip()
            team_away = away_elem.text.strip()
            
            if not team_home or not team_away or team_home in ["Home Team", "Away Team"]:
                continue
            
            # 🔍 استخراج الوقت
            time_elem = block.select_one('.anwp-match__time, .mt-time, .match-time, .time')
            match_time = time_elem.text.strip() if time_elem else ""
            
            match_string = f"{team_home}_{team_away}_{match_time}_{league_name_clean}"
            match_id = hashlib.md5(match_string.encode('utf-8')).hexdigest()
            
            
            # 🔍 استخراج المعلق
            commentator_elem = block.select_one('.match-commentator, .commentator, .mt-commentator, [class*="commentator"]')
            
            channel_elem = block.select_one('.match-channel, .channel, .mt-channel, [class*="channel"]')
            
            commentator_temp = commentator_elem.text.strip() if commentator_elem else "Not Assigned"
            commentator_temp = re.sub(r'(المعلق|معلق)\s*:\s*', '', commentator_temp).strip()

            channel_temp = channel_elem.text.strip() if channel_elem else "Not Broadcasted"
            channel_temp = re.sub(r'(القناة|قناة|القنوات الناقلة)\s*:\s*', '', channel_temp).strip()

            
            existing_match = database_structure["matches"][today_date][league_name_clean].get(match_id, {})
            
            # نحدث البيانات فقط إذا كانت القيم الجديدة ليست "فارغة"
            final_commentator = commentator_temp if commentator_temp != "Not Assigned" else existing_match.get("commentator", "غير مدرج")
            final_channel = [channel_temp] if channel_temp != "Not Broadcasted" else existing_match.get("channel", ["غير مدرج"])
            
            # إذا كانت البيانات ما زالت فارغة من الطرفين، نعتمد القيم الجديدة
            if final_commentator == "Not Assigned" and commentator_temp != "Not Assigned":
                final_commentator = commentator_temp

            # توليد معرف فريد للمباراة
            
            
            print(f"🔄 جاري معالجة مباراة: {team_home} 🆚 {team_away}")
            print(f"   📺 القناة: {final_channel} | 🎙️ المعلق: {commentator_temp}")
            
            database_structure["matches"][today_date][league_name_clean][match_id] = {
                "away_team": team_away,
                "home_team": team_home,
                "league": league_name_clean,
                "time": match_time,
                "channel": final_channel,
                "commentator": final_commentator
            }
            print("-" * 60)
            
        except Exception as e:
            print(f"⚠️ خطأ في معالجة مباراة: {e}")
            continue
    
    with open(output_filename, 'w', encoding='utf-8') as json_file:
        json.dump(database_structure, json_file, ensure_ascii=False, indent=4)
    
    print(f"\n🎉 تم الانتهاء بنجاح!")
    print(f"💾 تم حفظ قاعدة البيانات في ملف: {output_filename}")
    print("🚀 جاري رفع البيانات إلى Firebase...")
    # push_to_firebase_structured(database_structure)  # أزل التعليق إذا أردت الرفع
    #push_to_firebase_structured(database_structure)
    return database_structure

    
def extract_match_info(match_div, league_name):
    """استخراج بيانات مباراة واحدة من div.cin_cntnr"""
    try:
        # 1. استخراج معرف المباراة من الرابط
        match_link = match_div.find('a', href=True)
        match_url = match_link['href'] if match_link else ""
        match_id = match_url.split('/')[-2] if match_url else ""
        
        # 2. الفريق المضيف (القسم f)
        home_div = match_div.find('div', class_='f')
        home_team = ""
        home_logo = ""
        home_score = ""
        if home_div:
            home_link = home_div.find('a')
            if home_link:
                home_team = home_link.get_text(strip=True)
                img = home_link.find('img')
                if img and img.get('data-src'):
                    home_logo = img['data-src']
                    home_logo = fix_image_url(home_logo)

            score_elem = home_div.find('b')
            if score_elem:
                home_score = score_elem.get_text(strip=True).replace(' ', '')
        
        # 3. الفريق الضيف (القسم s)
        away_div = match_div.find('div', class_='s')
        away_team = ""
        away_logo = ""
        away_score = ""
        if away_div:
            away_link = away_div.find('a')
            if away_link:
                away_team = away_link.get_text(strip=True)
                img = away_link.find('img')
                if img and img.get('data-src'):
                    away_logo = img['data-src']
                    away_logo = fix_image_url(away_logo)

            score_elem = away_div.find('b')
            if score_elem:
                away_score = score_elem.get_text(strip=True).replace(' ', '')
        
        # 4. حالة المباراة والوقت
        status_elem = match_div.select_one('.m .status')
        match_status = status_elem.get_text(strip=True) if status_elem else ""
        
        # 5. استخراج الوقت والقنوات والملعب من match-aux
        aux_div = match_div.find('div', class_='match-aux')
        match_time = ""
        channels = []
        stadium = ""
        
        if aux_div:
            # البحث عن جميع الـ spans
            spans = aux_div.find_all('span')
            for span in spans:
                text = span.get_text(strip=True)
                # استخراج الوقت (يحتوي على تاريخ ووقت)
                if re.search(r'\d{2}-\d{2}-\d{4}', text):
                    match_time = text
                # استخراج الملعب (يحتوي على "استاد" أو "ملعب")
                elif 'استاد' in text or 'ملعب' in text:
                    stadium = text
                # استخراج القنوات (أي نص ليس تاريخاً ولا ملعباً ولا أيقونة)
                elif text and not re.search(r'\d{2}-\d{2}-\d{4}', text) and 'استاد' not in text and 'ملعب' not in text:
                    # تجاهل النصوص القصيرة جداً أو الأيقونات
                    if len(text) > 2:
                        channels.append(text)
            
            # إذا لم نجد قنوات بالطريقة أعلاه، نبحث عن أيقونة الشاشة
            if not channels:
                for span in spans:
                    # البحث عن أيقونة svg
                    svg = span.find('svg')
                    if svg and span.get_text(strip=True):
                        channels.append(span.get_text(strip=True))
        
        # 6. بناء البيانات النهائية
        return {
            "away_logo": away_logo,
            "away_team": away_team,
            "home_logo": home_logo,
            "home_team": home_team,
            "league": league_name,
            "league_logo": "",
            "time": match_time,
            "channel": channels if channels else ["غير مدرج"],
            "commentator": "غير مدرج",
            "status": match_status,
            "home_score": home_score,
            "away_score": away_score,
            "match_id": match_id,
            "stadium": stadium
        }
    except Exception as e:
        print(f"خطأ في استخراج مباراة: {e}")
        return None
    

    
def scrape_filgoal_matches(date_str=None):
    """
    استخراج بيانات المباريات من FilGoal لتاريخ معين.
    date_str: string بصيغة YYYY-MM-DD (افتراضي اليوم)
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    url = f"https://www.filgoal.com/matches/?date={date_str}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        response.encoding = 'utf-8'
    except Exception as e:
        print(f"خطأ في جلب الصفحة: {e}")
        return None
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # العثور على القسم الرئيسي
    match_viewer = soup.find('div', id='match-list-viewer')
    if not match_viewer:
        print("لم يتم العثور على قائمة المباريات")
        return None
    
    database_structure = {
        "leagues": {date_str: {}},
        "matches": {date_str: {}}
    }
    
    mc_blocks = match_viewer.find_all('div', class_='mc-block')
    
    for block in mc_blocks:
        # استخراج اسم الدوري
        h6 = block.find('h6')
        if not h6:
            continue
        league_name = h6.find('span').get_text(strip=True) if h6.find('span') else ""
        if not league_name:
            continue
        
        # إضافة الدوري إلى leagues
        if league_name not in database_structure["leagues"][date_str]:
            database_structure["leagues"][date_str][league_name] = {
                "logo": "",
                "name": league_name
            }
        
        # التأكد من وجود قائمة المباريات لهذا الدوري
        if league_name not in database_structure["matches"][date_str]:
            database_structure["matches"][date_str][league_name] = {}
        
        # استخراج المباريات
        match_divs = block.find_all('div', class_='cin_cntnr')
        for match_div in match_divs:
            match_data = extract_match_info(match_div, league_name)
            if match_data and match_data.get("match_id"):
                match_id = match_data.pop("match_id")
                database_structure["matches"][date_str][league_name][match_id] = match_data
    
    return database_structure


# ================== دالة الدمج الأساسية ==================


# ================== الحفظ والتنفيذ ==================
def save_to_json(data, filename):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"✅ تم حفظ البيانات في {filename}")

if __name__ == "__main__":
    print("="*50)
    print("بدء جلب البيانات من المصدرين...")
    print("="*50)

    # 1. جلب بيانات FilGoal (المصدر الرئيسي)
    filgoal_data = scrape_filgoal_matches()
    if filgoal_data:
        save_to_json(filgoal_data, "today_matches_filgoal.json")
    else:
        print("❌ فشل جلب بيانات FilGoal، لا يمكن الاستمرار.")
        exit(1)

    # 2. جلب بيانات AsGoal (المصدر الثانوي للمعلقين والقنوات)
    urlcomm = "https://as-goal.net/todays-match-commentators02/"
    
    
    asgoal_data = scrape_to_database_structure(urlcomm, "today_matches_as.json")
    
    # 3. الدمج
    print("\n🔄 جاري دمج البيانات من المصدرين...")
    final_data = merge_matches_data(filgoal_data, asgoal_data)

    # 4. حفظ النتيجة النهائية
    save_to_json(final_data, "final_matches_merged.json")
    print("\n🎉 اكتملت العملية بنجاح! الملف النهائي: final_matches_merged.json")
    push_to_firebase_structured(final_data)
    print("\n🎉 اكتملت الرفع الى قاعدة البيانات! ")
