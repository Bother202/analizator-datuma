import json
import csv
import io
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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'bs,hr,sr,en-US;q=0.7,en;q=0.3'
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
                
        dt = parser.parse(clean_lower, fuzzy=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CEST)
        else:
            dt = dt.astimezone(CEST)
        return dt
    except Exception:
        return None

def extract_image_upload_time(soup, session):
    """Pronalazi i izvlači vrijeme uploada ili modifikacije featured slike."""
    try:
        img_meta = soup.find('meta', property='og:image') or soup.find('meta', attrs={'name': 'twitter:image'})
        if not img_meta or not img_meta.get('content'):
            return None

        img_url = img_meta['content']
        
        # 1. HEAD zahtjev slikovnom serveru za Last-Modified zaglavlje
        try:
            head_res = session.head(img_url, timeout=5, allow_redirects=True)
            if head_res.status_code == 200 and 'Last-Modified' in head_res.headers:
                last_mod = head_res.headers['Last-Modified']
                return parse_date_safely(last_mod)
        except Exception:
            pass

        # 2. Ekstrakcija datuma iz same putanje u URL-u slike (npr. /uploads/2026/07/30/...)
        match_url = re.search(r'/uploads/(\d{4})/(\d{2})/(?:(\d{2})/)?', img_url)
        if match_url:
            year, month, day = match_url.group(1), match_url.group(2), match_url.group(3) or '01'
            dt = datetime(int(year), int(month), int(day))
            return dt.replace(tzinfo=CEST)

    except Exception:
        pass
    return None

def extract_article_dates(url):
    site_date = None
    img_date = None
    html = ""
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    
    # Preuzimanje HTML sadržaja
    try:
        response = session.get(url, timeout=10, allow_redirects=True)
        if response.status_code == 200 and len(response.text) > 1000:
            html = response.text
    except Exception:
        pass

    # Fallback za proxy ako je sajt direktno blokiran
    if not html or "Just a moment..." in html or "Attention Required!" in html:
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

    # ==========================================
    # 1. IZVLAČENJE VREMENA IZ SOURCE CODE-a
    # ==========================================
    
    # A) Meta tagovi
    meta_selectors = [
        {'property': 'article:published_time'}, {'name': 'article:published_time'},
        {'property': 'og:article:published_time'}, {'name': 'published_at'},
        {'property': 'published_at'}, {'name': 'publication_date'}, 
        {'name': 'pubdate'}, {'property': 'og:pubdate'},
        {'name': 'DC.date.issued'}, {'name': 'parsely-pub-date'}, {'itemprop': 'datePublished'}
    ]
    for selector in meta_selectors:
        meta = soup.find('meta', attrs=selector)
        if meta and meta.get('content'):
            site_date = parse_date_safely(meta['content'])
            if site_date:
                break

    # B) JSON-LD Metadati
    if not site_date:
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
                                    site_date = parsed
                                    break
                if site_date:
                    break
            except Exception:
                continue

    # C) HTML/Elementor Klase
    if not site_date:
        date_classes = [
            'elementor-post-info__item--type-date', 'post-info', 'date', 'news-date', 
            'time', 'published', 'article-date', 'datum', 'vrijeme', 'post-date', 
            'entry-date', 'clanak-datum', 'time-ago', 'publish-date', 'meta-date'
        ]
        for cls in date_classes:
            elements = soup.find_all(class_=re.compile(cls, re.I))
            for elem in elements:
                text = elem.text.strip()
                if re.search(r'\d{1,2}[\.\/-]\d{1,2}[\.\/-]\d{2,4}', text) or re.search(r'\d{1,2}:\d{2}', text):
                    site_date = parse_date_safely(text)
                    if site_date:
                        break
            if site_date:
                break

    # D) HTML5 <time> Tag
    if not site_date:
        time_tags = soup.find_all('time')
        for tag in time_tags:
            datetime_attr = tag.get('datetime') or tag.get('content') or tag.text.strip()
            if datetime_attr:
                site_date = parse_date_safely(datetime_attr)
                if site_date:
                    break

    # E) HtmlDate Fallback
    if not site_date:
        extracted_date_str = find_date(html)
        if extracted_date_str:
            site_date = parse_date_safely(extracted_date_str)

    # ==========================================
    # 2. IZVLAČENJE VREMENA SA FEATURED SLIKE
    # ==========================================
    img_date = extract_image_upload_time(soup, session)

    return site_date, img_date

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
        placeholder="https://www.vecernji.ba/...\nhttps://www.slobodna-bosna.ba/...\nhttps://www.fokus.ba/..."
    )

    col1, _ = st.columns([1, 4])
    with col1:
        sort_option = st.radio("Sortiranje po vremenu:", ("Najnovije prvo", "Najstarije prvo"))
    
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
            site_dt, img_dt = extract_article_dates(url)
            
            # Određivanje primarnog datuma za sortiranje (Primarno Source Code, sekundarno Slika)
            primary_dt = site_dt if site_dt else img_dt
            
            results.append({
                'url': url,
                'site_date': site_dt,
                'img_date': img_dt,
                'primary_date': primary_dt
            })
            progress_bar.progress((idx + 1) / len(urls))

        status_text.success("Analiza završena!")

        # Razdvajanje na uspješno analizirane i neuspješne
        valid_results = [r for r in results if r['primary_date'] is not None]
        failed_results = [r for r in results if r['primary_date'] is None]

        # Sortiranje primarno po datumu iz Source Code-a (ili slikovnog rezervnog)
        reverse_sort = True if sort_option == "Najnovije prvo" else False
        valid_results.sort(key=lambda x: x['primary_date'], reverse=reverse_sort)

        final_data = valid_results + failed_results

        # Priprema tabele za prikaz
        table_data = []
        csv_data = []

        for idx, item in enumerate(final_data, 1):
            site_str = item['site_date'].strftime('%Y-%m-%d %H:%M:%S CEST') if item['site_date'] else "Nije pronađeno"
            img_str = item['img_date'].strftime('%Y-%m-%d %H:%M:%S CEST') if item['img_date'] else "Nije pronađeno"

            table_data.append({
                "#": idx,
                "Vrijeme u Kôdu (Članak)": site_str,
                "Vrijeme Slike (Procjena)": img_str,
                "URL": item['url']
            })

            csv_data.append({
                "Redni Broj": idx,
                "Vrijeme u Kodu (Clanak)": site_str,
                "Vrijeme Slike (Procjena)": img_str,
                "URL": item['url']
            })

        # Prikaz tabele na stranici
        st.table(table_data)

        # Generisanje CSV fajla za preuzimanje
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["Redni Broj", "Vrijeme u Kodu (Clanak)", "Vrijeme Slike (Procjena)", "URL"])
        writer.writeheader()
        writer.writerows(csv_data)
        csv_bytes = output.getvalue().encode('utf-8-sig')

        st.download_button(
            label="📥 Preuzmi rezultate u CSV formatu",
            data=csv_bytes,
            file_name=f"analiza_vremena_objave_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            type="secondary"
        )

if __name__ == "__main__":
    main()
