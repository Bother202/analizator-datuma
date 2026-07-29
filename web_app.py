import json
import csv
import re
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup
from dateutil import parser
from htmldate import find_date
import streamlit as st
import cloudscraper

# Vremenska zona za našu regiju (CEST / UTC+2)
CEST = timezone(timedelta(hours=2))

# Mapa mjeseci na našim jezicima za sigurno parsiranje
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
    """Pretvara relativno vrijeme poput 'Prije 2h' ili 'prije 45 min' u datetime."""
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
        clean_str = re.sub(r'(\d{4})\d$', r'\1', clean_str) # Uklanja višku nulu na kraju godine (Slobodna Bosna)
        
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
    
    # -------------------------------------------------------------
    # 1. POKUŠAJ: Direktan upit preko Cloudscrapera
    # -------------------------------------------------------------
    try:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )
        response = scraper.get(url, timeout=10)
        if response.status_code == 200 and len(response.text) > 2000:
            html = response.text
    except Exception:
        pass

    # -------------------------------------------------------------
    # 2. POKUŠAJ (JINA PROXY FALLBACK): Ako je Cloudflare blokirao server
    # -------------------------------------------------------------
    if not html or "Just a moment..." in html or "Enable JavaScript" in html:
        try:
            proxy_url = f"https://r.jina.ai/{url}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36',
                'X-With-Generated-Alt': 'true'
            }
            res = requests.get(proxy_url, headers=headers, timeout=15)
            if res.status_code == 200:
                html = res.text
        except Exception as e:
            print(f"[GREŠKA PROXY] {url}: {e}")

    if not html:
        return None

    soup = BeautifulSoup(html, 'html.parser')

    # -------------------------------------------------------------
    # LOGIKA ZA EKSTRAKCIJU DATUMA
    # -------------------------------------------------------------

    # A) Specifično za Slobodnu Bosnu (Izbjegavanje lažnog meta taga)
    if "slobodna-bosna.ba" in url:
        sb_elem = soup.find('div', class_='info') or \
                  soup.find('span', class_='date') or \
                  soup.find('div', class_=re.compile(r'mini_market|vijest|article', re.I))
        if sb_elem:
            text_match = re.search(r'(\d{1,2}\.\s*[A-Za-zčćšžđČĆŠŽĐ]+\.\s*\d{4}\d?)|(prije\s+.*)', sb_elem.text, re.I)
            if text_match:
                dt = parse_date_safely(text_match.group(0))

    # B) JSON-LD (Dnevno.hr i standardni portali)
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

    # C) Meta tagovi (og:article:published_time, article:published_time, etc.)
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

    # D) HTML5 <time> Tagovi
    if not dt:
        time_tags = soup.find_all('time')
        for tag in time_tags:
            datetime_attr = tag.get('datetime') or tag.get('content') or tag.text.strip()
            if datetime_attr:
                dt = parse_date_safely(datetime_attr)
                if dt:
                    break

    # E) Pretraživanje datuma u tekstu (Za Jina Proxy čist tekst)
    if not dt:
        text_content = soup.get_text()
        date_match = re.search(r'(\d{1,2}\.\d{1,2}\.\d{4}\.?\s*(?:u\s*)?\d{1,2}:\d{2})|(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', text_content)
        if date_match:
            dt = parse_date_safely(date_match.group(0))

    # F) Fallback na htmldate biblioteku
    if not dt:
        extracted_date_str = find_date(html)
        if extracted_date_str:
            dt = parse_date_safely(extracted_date_str)

    # Normalizacija u CEST vremensku zonu
    if dt:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CEST)
        else:
            dt = dt.astimezone(CEST)
        return dt

    return None

# ==============================================================================
# STREAMLIT INTERFEJS
# ==============================================================================
def main():
    st.set_page_config(page_title="Analizator Vremena Objave Članaka", page_icon="⏱️", layout="wide")
    st.title("⏱️ Analizator Vremena Objave Članaka")
    st.write("Unesite listu URL-ova kako biste izvučeni datum i vrijeme objave poredali hronološki.")

    urls_input = st.text_area("Unesite URL-ove ovdje (svaki u novi red):", height=180, placeholder="https://www.dnevno.hr/...\nhttps://www.slobodna-bosna.ba/...")

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
