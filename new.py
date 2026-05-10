import json
import time
import os
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager # مكتبة مهمة للتحميل التلقائي
 virtues BeautifulSoup
from urllib.parse import urljoin

# جلب رابط Firebase من متغيرات البيئة (أكثر أماناً)
FIREBASE_URL = os.getenv('FIREBASE_URL', 'https://laith-5c47d-default-rtdb.asia-southeast1.firebasedatabase.app/BeinEvents')

def get_today_date():
    return datetime.now().strftime("%Y-%m-%d")

def get_today_matches_url():
    return "https://www.kooora.com/%D9%83%D8%B1%D8%A9-%D8%A7%D9%84%D9%82%D8%AF%D9%85/%D9%85%D8%A8%D8%A7%D8%B1%D9%8A%D8%A7%D8%AA-%D8%A7%D9%84%D9%82%D8%AF%D9%85"

def extract_match_data(soup):
    json_matches = {}
    scripts = soup.find_all('script', type='application/ld+json')
    for script in scripts:
        try:
            if script.string:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'SportsEvent':
                    match_url = data.get('url', '')
                    if match_url:
                        json_matches[match_url] = {
                            "home_name": data.get('homeTeam', {}).get('name'),
                            "home_logo": data.get('homeTeam', {}).get('logo'),
                            "away_name": data.get('awayTeam', {}).get('name'),
                            "away_logo": data.get('awayTeam', {}).get('logo'),
                        }
        except:
            continue
    
    leagues = {}
    league_headers = soup.find_all('a', class_='fco-competition-section__header')
    for header in league_headers:
        league_name_elem = header.find('span', class_='fco-competition-section__header-name')
        if not league_name_elem: continue
        league_name = league_name_elem.get_text().strip()
        logo_img = header.find('img', class_='fco-image__image')
        leagues[league_name] = logo_img['src'] if logo_img and logo_img.get('src') else ""

    matches = []
    match_items = soup.find_all('div', class_='fco-match-list-item')
    
    for item in match_items:
        match_link = ""
        link_tag = item.find('a', class_='fco-match-data')
        if link_tag and link_tag.get('href'):
            match_link = urljoin("https://www.kooora.com", link_tag['href'])
        
        # تحديد الدوري
        league_name = "بطولة عامة"
        league_logo = ""
        parent_section = item.find_parent('div', class_='match-list_livescores-match-list__section__n742K')
        if parent_section:
            header = parent_section.find('a', class_='fco-competition-section__header')
            if header:
                league_elem = header.find('span', class_='fco-competition-section__header-name')
                if league_elem:
                    league_name = league_elem.get_text().strip()
                    league_logo = leagues.get(league_name, "")
        
        # الحالة والوقت
        status = "لم تبدأ"
        match_status = item.get('data-match-status', '')
        if match_status == 'LIVE': status = "مباشر"
        elif match_status == 'RESULT': status = "انتهت"
        
        status_elem = item.find('div', class_='fco-match-status')
        if status_elem:
            text = status_elem.get_text().strip()
            if text in ["انتهت", "استراحة", "مباشر"]: status = text
        
        match_time = ""
        time_elem = item.find('time', class_='fco-match-start-time')
        if time_elem: match_time = time_elem.get_text().strip()
        minutes_elem = item.find('div', class_='fco-match-minutes__value')
        if minutes_elem: match_time = minutes_elem.get_text().strip()
        
        # الفرق واللوجو
        jm = json_matches.get(match_link, {})
        home_name = jm.get('home_name') or "غير معروف"
        home_logo = jm.get('home_logo') or ""
        away_name = jm.get('away_name') or "غير معروف"
        away_logo = jm.get('away_logo') or ""
        
        # القنوات الناقلة
        channels_set = set()
        for ch in item.find_all('div', class_='fco-tv-channel__name'):
            channels_set.add(ch.get_text().strip())
        for ch in item.find_all('a', class_='fco-tv-channel'):
            name = ch.find('div', class_='fco-tv-channel__name')
            if name: channels_set.add(name.get_text().strip())
        
        matches.append({
            "league": league_name,
            "league_logo": league_logo,
            "status": status,
            "home_team": home_name,
            "home_logo": home_logo,
            "away_team": away_name,
            "away_logo": away_logo,
            "channel": sorted(list(channels_set)),
            "time": match_time
        })
    
    unique_matches = []
    seen = set()
    for m in matches:
        key = (m['league'], m['home_team'], m['away_team'])
        if key not in seen:
            seen.add(key)
            unique_matches.append(m)
    return unique_matches

def push_to_firebase(data, date_str):
    url = f"{FIREBASE_URL}/{date_str}.json"
    try:
        response = requests.put(url, json=data, timeout=20)
        if response.status_code < 400:
            print(f"✅ تم تحديث {len(data)} مباراة في Firebase")
        else:
            print(f"❌ خطأ Firebase: {response.status_code}")
    except Exception as e:
        print(f"❌ فشل الاتصال بـ Firebase: {e}")

def scrape_kooora():
    chrome_options = Options()
    chrome_options.add_argument("--headless") # ضروري للعمل في السيرفر
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    # استخدام webdriver-manager لضمان التوافق
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    try:
        url = get_today_matches_url()
        print(f"⏳ جاري فحص المباريات من: {url}")
        driver.get(url)
        time.sleep(10) # انتظار تحميل الجافا سكريبت
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        matches = extract_match_data(soup)
        
        if matches:
            push_to_firebase(matches, get_today_date())
        else:
            print("⚠️ لم يتم العثور على مباريات حالياً.")
            
    finally:
        driver.quit()

if __name__ == "__main__":
    scrape_kooora()
