import json
import csv
import re
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup
from dateutil import parser
from htmldate import find_date
import streamlit as st

# Vremenska zona CEST (UTC+2)
CEST = timezone(timedelta(hours=2))

MONTHS_MAP = {
    'januar': '01', 'januara': '01', 'siječanj': '01', 'siječnja': '01', 'jan': '01', 'january': '01',
    'februar': '02', 'februara': '02', 'veljača': '02', 'veljače': '02', 'feb': '02', 'february': '02',
    'mart': '03', 'marta': '03', 'ožujak': '03', 'ožujka': '03', 'mar': '03', 'march': '03',
    'april': '04', 'aprila': '04', 'travanj': '04', 'travnja': '04', 'apr': '04',
    'maj': '05', 'maja': '05', 'svibanj': '05', 'svibnja': '05', 'may': '05',
    'juni': '06', 'juna': '06', 'lipanj': '06', 'lipnja': '06', 'jun': '06', 'june': '06',
    'juli': '07', 'jula': '07', 'jul': '07', 'srpanj': '07', 'srpnja': '07', 'july': '07',
    'august': '08', 'augusta': '08', 'kolovoz': '08', 'kolovoza': '08', 'aug': '08',
    'septembar': '09', 'septembra': '09', 'rujan': '09', 'rujna': '09', 'sep': '09', 'september': '09',
    'oktobar': '10', 'oktobara': '10', 'listopad': '10', 'listopada': '10', 'okt': '10', 'october': '10',
    'novembar': '11', 'novembra': '11', 'studeni': '11', 'studenog': '11', 'nov': '11', 'november': '11',
    'decembar': '12', 'decembra': '12', 'prosinac': '12', 'prosinca': '12', 'dec': '12', 'december': '12'
}

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'bs,hr,sr,en-US;q=0.7,en;q=0.3',
}

def parse_relative_time(text):
    now = datetime.now(CEST)
    text_lower = text.lower()
    
    match_hours = re.search(r'prije\s+(\d+)\s*(h|sat|sata|sati)', text_lower)
    if match_hours:
        return now - timedelta(hours=int(match_hours.group(1)))
        
    match_mins = re.search(r'prije\s+(\d+)\s*(m|min|minuta|minute)', text_lower)
    if match_mins:
        return now - timedelta(minutes=int(match_mins.group(1)))

    match_days = re.search(r'prije\s+(\d+)\s*(d|dan|dana)', text_lower)
    if match_days:
        return now - timedelta(days=int(match_days.group(1)))

    return None

def parse_date_safely(date_str):
    if not date_str:
        return None
        
    rel_dt = parse_relative_time(date_str)
    if rel_dt:
        return rel_dt

    try:
        clean_str = date_str.strip()
        clean_str = re.sub(r'(\d{1,2})[\/\.](\d{1,2})[\/\.](\d{4})\.?\s*(?:u|@)?\s*(\d{1,2}:\d{2})', r'\3-\2-\1 \4', clean_str)
        clean_str = re.sub(r'(\d{4})\d$', r'\1', clean_str)
        
        clean_lower = clean_str.lower()
        for month_name, month_num in MONTHS_MAP.items():
            pattern = r'\b' + re.escape(month_name) + r'\b|\b' + re.escape(month_name) + r'\.'
            if re.search(pattern, clean_lower):
                clean_lower = re.sub(pattern, month_num, clean_lower)
                break
                
        return parser.parse(clean_lower, fuzzy=True)
    except Exception:
        return None

def extract_image_upload_time(soup, session):
    """Izvlači vrijeme uploada featured slike preko Meta tagova i Last-Modified HTTP zaglavlja."""
    try:
        # Pronalaženje glavne slike (og:image ili twitter:image)
        img_meta = soup.find('meta', property='og:image') or soup.find('meta', attrs={'name': 'twitter:image'})
        if not img_meta or not img_meta.get('content'):
            return None

        img_url = img_meta['content']
        
        # 1. Pokušaj izvlačenja datuma iz URL-a slike (čest slučaj kod WordPressa: /uploads/2026/07/filename.jpg)
        match_url = re.search(r'/uploads/(\d{4})/(\d{2})/(?:(\d{2})/)?', img_url)
        
        # 2. Slanje HEAD zahtjeva medijskom serveru za preuzimanje Last-Modified zaglavlja
        head_res = session.head(img_url, timeout=5, allow_redirects=True)
        if head_res.status_code == 200 and 'Last-Modified' in head_res.headers:
            last_mod = head_res.headers['Last-Modified']
            dt = parser.parse(last_mod)
            return dt
            
    except Exception:
        pass
    return None

def extract_published_date(url):
    dt = None
    source_type = "Članak / Kôd"
    html = ""
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    
    # 1. DOHVAT HTML SADRŽAJA
    try:
        response = session.get(url, timeout=12, allow_redirects=True)
        if response.status_code == 200 and len(response.text) > 1000:
            html = response.text
    except Exception:
        pass

    if not html or "Just a moment..." in html:
        proxy_urls = [f"https://r.jina.ai/{url}", f"https://api.allorigins.win/raw?url={url}"]
        for p_url in proxy_urls:
            try:
                r = session.get(p_url, timeout=12)
                if r.status_code == 200 and len(r.text) > 1000:
                    html = r.text
                    break
            except Exception:
                continue

    if not html:
        return None, None

    soup = BeautifulSoup(html, 'html.parser')

    # A) SPECIFIČNO ZA SLOBODNU BOSNU
    if "slobodna-bosna.ba" in url:
        sb_elem = soup.find('div', class_='info') or \
                  soup.find('span', class_='date') or \
                  soup.find('div', class_=re.compile(r'mini_market|vijest|article', re.I))
        if sb_elem:
            text_match = re.search(r'(\d{1,2}\.\s*[A-Za-zčćšžđČĆŠŽĐ]+\.\s*\d{4}\d?)|(prije\s+.*)', sb_elem.text, re.I)
            if text_match:
                dt = parse_date_safely(text_match.group(0))

    # B) META TAGOVI
    if not dt:
        meta_selectors = [
            {'name': 'published_at'}, {'property': 'published_at'},
            {'property': 'article:published_time'}, {'property': 'og:article:published_time'},
            {'name': 'publication_date'}, {'name': 'pubdate'}, {'property': 'og:pubdate'},
            {'name': 'DC.date.issued'}, {'name': 'parsely-pub-date'}, {'itemprop': 'datePublished'}
        ]
        for selector in meta_selectors:
            meta = soup.find('meta', attrs=selector)
            if meta and meta.get('content'):
                dt = parse_date_safely(meta['content'])
                if dt:
                    break

    # C) JSON-LD METADATI
    if not dt:
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict):
                        graph = item.get('@graph', [item])
                        for node in graph:
                            if isinstance(node, dict) and 'datePublished' in node:
                                parsed = parse_date_safely(node['datePublished'])
                                if parsed:
                                    dt = parsed
                                    break
                if dt:
                    break
            except Exception:
                continue

    # D) HTML I ELEMENTOR KLASSE
    if not dt:
        date_classes = [
            'elementor-post-info__item--type-date', 'post-info', 'date', 'news-date', 
            'time', 'published', 'article-date', 'datum', 'vrijeme', 'post-date', 'entry-date'
        ]
        for cls in date_classes:
            elements = soup.find_all(class_=re.compile(cls, re.I))
            for elem in elements:
                text = elem.text.strip()
                if re.search(r'\d{1,2}[\.\/-]\d{1,2}[\.\/-]\d{2,4}', text) or re.search(r'\d{1,2}:\d{2}', text):
                    dt = parse_date_safely(text)
                    if dt:
                        break
            if dt:
                break

    # E) HTML5 <time> TAG
    if not dt:
        time_tags = soup.find_all('time')
        for tag in time_tags:
            datetime_attr = tag.get('datetime') or tag.get('content') or tag.text.strip()
            if datetime_attr:
                dt = parse_date_safely(datetime_attr)
                if dt:
                    break

    # F) FALLBACK HTMLDATE
    if not dt:
        extracted_date_str = find_date(html)
        if extracted_date_str:
            dt = parse_date_safely(extracted_date_str)

    # G) NEMA VREMENA (Samo datum sa 00:00:00) ILI NEMA DATUMA UOPŠTE -> POKUŠAJ PREKO FEATURED SLIKE
    if not dt or (dt.hour == 0 and dt.minute == 0 and dt.second == 0):
        img_dt = extract_image_upload_time(soup, session)
        if img_dt:
            dt = img_dt
            source_type = "Featured Slika (Procjena)"

    # Pretvaranje u CEST vremensku zonu
    if dt:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CEST)
        else:
            dt = dt.astimezone(CEST)
        return dt, source_type

    return None, "Nije pronađeno"

# ==============================================================================
# STREAMLIT INTERFEJS
# ==============================================================================
def main():
    st.set_page_config(page_title="Analizator Vremena Objave Članaka", page_icon="⏱️", layout="wide")
    
    st.title("⏱️ Analizator Vremena Objave Članaka")
    st.write("Unesite URL-ove novinskih članaka (svaki u novi red):")

    urls_input = st.text_area(
        "Unesite URL-ove ovdje:", 
        height=180, 
        placeholder="https://www.slobodna-bosna.ba/...\nhttps://www.fokus.ba/...\nhttps://www.dnevno.hr/..."
    )

    col1, _ = st.columns([1, 4])
    with col1:
        sort_option = st.radio("Sortiranje:", ("Najnovije prvo", "Najstarije prvo"))
    
    if st.button("POKRENI ANALIZU", type="primary"):
        urls = [line.strip() for line in urls_input.splitlines() if line.strip() and not line.strip().startswith('#')]
        
        if not urls:
            st.warning("Molimo unesite barem jedan ispravan URL.")
            return

        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()

        for idx, url in enumerate(urls):
            status_text.text(f"Analiziram [{idx+1}/{len(urls)}]: {url}")
            pub_date, source_type = extract_published_date(url)
            results.append({'url': url, 'date': pub_date, 'source': source_type})
            progress_bar.progress((idx + 1) / len(urls))

        status_text.success("Analiza završena!")

        valid_results = [r for r in results if r['date'] is not None]
        failed_results = [r for r in results if r['date'] is None]

        reverse_sort = True if sort_option == "Najnovije prvo" else False
        valid_results.sort(key=lambda x: x['date'], reverse=reverse_sort)

        final_data = valid_results + failed_results

        table_data = []
        for idx, item in enumerate(final_data, 1):
            table_data.append({
                "#": idx,
                "Datum i Vrijeme (CEST)": item['date'].strftime('%Y-%m-%d %H:%M:%S CEST') if item['date'] else "-",
                "Izvor Vremena": item['source'],
                "URL": item['url']
            })

        st.table(table_data)

if __name__ == "__main__":
    main()
