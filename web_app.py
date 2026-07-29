import json
import csv
import re
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from dateutil import parser
from htmldate import find_date
import streamlit as st
import cloudscraper

# Vremenska zona za našu regiju (CEST / UTC+2)
CEST = timezone(timedelta(hours=2))

MONTHS_MAP = {
    'januar': '01', 'januara': '01', 'siječanj': '01', 'siječnja': '01',
    'februar': '02', 'februara': '02', 'veljača': '02', 'veljače': '02',
    'mart': '03', 'marta': '03', 'ožujak': '03', 'ožujka': '03',
    'april': '04', 'aprila': '04', 'travanj': '04', 'travnja': '04',
    'maj': '05', 'maja': '05', 'svibanj': '05', 'svibnja': '05',
    'juni': '06', 'juna': '06', 'lipanj': '06', 'lipnja': '06',
    'juli': '07', 'jula': '07', 'jul': '07', 'srpanj': '07', 'srpnja': '07',
    'august': '08', 'augusta': '08', 'kolovoz': '08', 'kolovoza': '08',
    'septembar': '09', 'septembra': '09', 'rujan': '09', 'rujna': '09',
    'oktobar': '10', 'oktobara': '10', 'listopad': '10', 'listopada': '10',
    'novembar': '11', 'novembra': '11', 'studeni': '11', 'studenog': '11',
    'decembar': '12', 'decembra': '12', 'prosinac': '12', 'prosinca': '12'
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
        clean_str = re.sub(r'(\d{4})\d$', r'\1', clean_str)
        
        clean_lower = clean_str.lower()
        for month_name, month_num in MONTHS_MAP.items():
            if month_name in clean_lower:
                clean_lower = clean_lower.replace(month_name, month_num)
                break
                
        return parser.parse(clean_lower, fuzzy=True)
    except Exception:
        return None

def extract_published_date(url):
    dt = None
    html = ""
    
    try:
        # Inicijalizacija scrapera koji prolazi Cloudflare challenge
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        response = scraper.get(url, timeout=15)
        if response.status_code == 200:
            html = response.text
    except Exception as e:
        print(f"[GREŠKA CLOUDSCRAPER] {url}: {e}")
        return None

    if not html:
        return None

    soup = BeautifulSoup(html, 'html.parser')

    # 1. Slobodna Bosna specifičnost
    if "slobodna-bosna.ba" in url:
        sb_elem = soup.find('div', class_='info') or \
                  soup.find('span', class_='date') or \
                  soup.find('div', class_=re.compile(r'mini_market|vijest|article', re.I))
        
        if sb_elem:
            text_match = re.search(r'(\d{1,2}\.\s*[A-Za-zčćšžđČĆŠŽĐ]+\.\s*\d{4}\d?)|(prije\s+.*)', sb_elem.text, re.I)
            if text_match:
                dt = parse_date_safely(text_match.group(0))

    # 2. JSON-LD
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

    # 3. Meta tagovi
    if not dt and "slobodna-bosna.ba" not in url:
        meta_selectors = [
            {'property': 'article:published_time'},
            {'property': 'og:article:published_time'},
            {'name': 'publication_date'},
            {'name': 'DC.date.issued'},
            {'name': 'parsely-pub-date'},
            {'itemprop': 'datePublished'}
        ]
        for selector in meta_selectors:
            meta = soup.find('meta', attrs=selector)
            if meta and meta.get('content'):
                dt = parse_date_safely(meta['content'])
                if dt:
                    break

    # 4. HTML5 <time> tagovi
    if not dt:
        time_tags = soup.find_all('time')
        for tag in time_tags:
            datetime_attr = tag.get('datetime') or tag.get('content') or tag.text.strip()
            if datetime_attr:
                dt = parse_date_safely(datetime_attr)
                if dt:
                    break

    # 5. Fallback na htmldate
    if not dt:
        extracted_date_str = find_date(html)
        if extracted_date_str:
            dt = parse_date_safely(extracted_date_str)

    if dt:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CEST)
        else:
            dt = dt.astimezone(CEST)
        return dt

    return None

def main():
    st.set_page_config(page_title="Analizator Vremena Objave Članaka", page_icon="⏱️", layout="wide")
    st.title("⏱️ Analizator Vremena Objave Članaka")
    
    urls_input = st.text_area("Unesite URL-ove ovdje:", height=180, placeholder="https://www.dnevno.hr/...\nhttps://www.slobodna-bosna.ba/...")

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
            pub_date = extract_published_date(url)
            results.append({'url': url, 'date': pub_date})
            progress_bar.progress((idx + 1) / len(urls))

        status_text.success("Analiza uspješno završena!")

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
                "Status": "Pronađeno" if item['date'] else "Nije pronađeno",
                "URL": item['url']
            })

        st.table(table_data)

if __name__ == "__main__":
    main()
