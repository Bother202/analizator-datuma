import json
import re
import requests
from bs4 import BeautifulSoup
from dateutil import parser
from htmldate import find_date
from datetime import datetime, timezone, timedelta

CEST = timezone(timedelta(hours=2))

# Napredna zaglavlja koja simuliraju pravi web preglednik da ih Cloudflare ne blokira
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'hr-HR,hr;q=0.9,en-US;q=0.8,en;q=0.7,bs;q=0.6,sr;q=0.5',
    'Cache-Control': 'max-age=0',
    'Upgrade-Insecure-Requests': '1'
}

def extract_published_date(url):
    dt = None
    try:
        # Korištenje Session-a pomaže kod portala sa zaštitama poput Dnevno.hr
        session = requests.Session()
        session.headers.update(HEADERS)
        
        response = session.get(url, timeout=12, allow_redirects=True)
        response.raise_for_status()
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')

        # 1. JSON-LD (Standard za većinu novinskih portala)
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
                                dt = parse_date_safely(node['datePublished'])
                                if dt:
                                    break
                if dt:
                    break
            except Exception:
                continue

        # 2. Meta tagovi (Dnevno.hr drži datum u article:published_time ili publication_date)
        if not dt:
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

        # 3. HTML5 <time> tagovi
        if not dt:
            time_tags = soup.find_all('time')
            for tag in time_tags:
                datetime_attr = tag.get('datetime') or tag.get('content') or tag.text.strip()
                if datetime_attr:
                    dt = parse_date_safely(datetime_attr)
                    if dt:
                        break

        # 4. Fallback na htmldate biblioteku
        if not dt:
            extracted_date_str = find_date(html)
            if extracted_date_str:
                dt = parse_date_safely(extracted_date_str)

        # Pretvaranje u CEST vremensku zonu
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=CEST)
            else:
                dt = dt.astimezone(CEST)
            return dt

    except Exception as e:
        print(f"[GREŠKA PRISTUPA] {url}: {e}")
        
    return None
