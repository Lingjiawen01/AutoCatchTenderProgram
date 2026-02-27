import os
import time
import requests
import re
import random
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- 配置区 ---
TELEGRAM_TOKEN = "8249171192:AAGEjyCYuF2_EqrIa6cLRIWkIuSuB0co7VY"
USER_IDS = ["5101247595","8643954314","7763852448"] 
DB_FILE = "seen_projects.txt"

SITES = [
    {"name": "JKR Sarawak", "url": "https://jkr.sarawak.gov.my/web/subpage/tender_and_quotation_list/tender", "id_tag": "T/", "type": "text"},
    {"name": "RECODA Sarawak", "url": "https://recoda.gov.my/tender/", "id_tag": "RCDA/", "type": "text"},
    {"name": "SEB (Sarawak Energy)", "url": "https://os.sarawakenergy.com.my/etender/", "id_tag": "Doc", "type": "seb"}, 
    {"name": "JBALB Sarawak", "url": "https://jbalb.sarawak.gov.my/web/subpage/webpage_view/89", "id_tag": "T/JBALB/", "type": "text"},
    {"name": "Sacofa", "url": "https://www.sacofa.com.my/index.php/archived-tender-notice", "id_tag": "Reference Number", "type": "text"},
    {"name": "KKDW (Rural Link)", "url": "https://www.rurallink.gov.my/tender-sebut-harga/iklan-tawaran-tender/", "id_tag": "KKDW", "type": "table"}
]

# --- 增强版逻辑：物理检查重复 ---
def is_duplicate(ukey):
    if not os.path.exists(DB_FILE): 
        return False
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        # 使用 strip() 彻底清除每一行两端的不可见字符（空格、换行等）
        # 这样即便文件里有粘连，逻辑比对也会更健壮
        seen_ids = {line.strip() for line in f if line.strip()}
        return ukey.strip() in seen_ids

def save_to_db(ukey):
    ukey = ukey.strip()
    if not is_duplicate(ukey):
        with open(DB_FILE, 'a+', encoding='utf-8') as f:
            # a+ 模式让我们可以先检查文件末尾状态
            f.seek(0, 2)  # 移到文件末尾
            if f.tell() > 0:
                f.seek(f.tell() - 1)
                last_char = f.read(1)
                # 如果最后一个字符不是换行符，先补一个换行符，防止粘连
                if last_char != '\n':
                    f.write('\n')
            
            # 写入新的 ID 并强制换行
            f.write(f"{ukey}\n")
        return True
    return False

# --- 增强版日期系统 ---
def validate_and_filter_2026(date_str):
    if not date_str or "Refer" in date_str: return False, "Refer Portal"
    clean_date = re.sub(r'[^\d/-]', '', date_str)
    formats = ["%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"]
    for fmt in formats:
        try:
            dt = datetime.strptime(clean_date, fmt)
            if dt.year < 100: dt = dt.replace(year=2000 + dt.year)
            if dt.year == 2026: return True, dt.strftime("%d/%m/%Y")
        except ValueError: continue
    return False, "Invalid Date"

def smart_date_parser(text):
    if not text: return None
    clean_text = text.upper()
    month_map = {
        "JANUARI": "01", "JANUARY": "01", "FEBRUARI": "02", "FEBRUARY": "02",
        "MAC": "03", "MARCH": "03", "APRIL": "04", "MEI": "05", "MAY": "05",
        "JUN": "06", "JUNE": "06", "JULAI": "07", "JULY": "07", "OGOS": "08", "AUGUST": "08",
        "SEPTEMBER": "09", "OKTOBER": "10", "OCTOBER": "10", "NOVEMBER": "11", "DISEMBER": "12", "DECEMBER": "12"
    }
    verbose_pattern = r'(\d{1,2})\s*(?:ST|ND|RD|TH)?\s+(JANUARI|FEBRUARI|MAC|APRIL|MEI|JUN|JULAI|OGOS|SEPTEMBER|OKTOBER|NOVEMBER|DISEMBER|JANUARY|FEBRUARY|MARCH|MAY|JUNE|JULY|AUGUST|OCTOBER|DECEMBER)\s+(\d{4})'
    v_match = re.search(verbose_pattern, clean_text)
    if v_match:
        d, m_name, y = v_match.groups()
        return f"{d}/{month_map.get(m_name)}/{y}"
    date_matches = re.findall(r'(\d{1,2}[/-]\d{1,2}[/-]2026)', clean_text)
    return date_matches[-1] if date_matches else None

def get_long_title(lines, start_idx, search_range=8):
    candidates = []
    for i in range(start_idx, min(len(lines), start_idx + search_range)):
        line = lines[i].strip()
        upper_l = line.upper()
        if len(line) < 15: continue 
        if any(k in upper_l for k in ["SPECIALIZATION", "CLASS", "RM ", "BOARD", "TENDER NO", "NEW !", "APPLY", "CLOSING DATE"]): continue
        score = len(line) + (150 if any(w in upper_l for w in ["PROJECT", "PROPOSED", "CADANGAN", "WORKS", "CONSTRUCTION", "PEMBINAAN", "SUPPLY"]) else 0)
        candidates.append((score, line))
    return sorted(candidates, key=lambda x: x[0], reverse=True)[0][1] if candidates else "Check Portal"

def send_alert(site_name, t_id, title, loc, board, closing, url):
    message = f"📢 *NEW TENDER: {site_name}*\n━━━━━━━━━━━━━━━\n📋 *Project:* `{title}`\n\n🆔 *Ref:* `{t_id}`\n📍 *Loc:* {loc}\n🏛️ *Dept:* {board}\n📅 *Due:* {closing}\n━━━━━━━━━━━━━━━\n🔗 [Open Official Portal]({url})"
    for user in USER_IDS:
        api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try: requests.post(api, data={"chat_id": user, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=15)
        except: pass

class SiteParser:
    @staticmethod
    def jbalb_sarawak(block, lines, idx):
        id_match = re.search(r'(T/JBALB/\d+/[A-Z.]+.\d+)', block)
        t_id = id_match.group() if id_match else "Unknown"
        title = lines[idx+1].strip() if len(lines) > idx+1 else "N/A"
        raw_date = smart_date_parser(block)
        return t_id, title, "Water Supply", "JBALB Sarawak", raw_date

    @staticmethod
    def jkr_sarawak(block, lines, idx):
        id_match = re.search(r'(T/\d+/\d+/\d+)', block)
        t_id = id_match.group() if id_match else "Unknown"
        title = get_long_title(lines, idx)
        closing_info = re.search(r'Closing Date\s*(.*)', block, re.I)
        raw_date = smart_date_parser(closing_info.group(1) if closing_info else block)
        loc = "Check Portal"
        for i in range(idx, min(len(lines), idx+10)):
            if "PROJECT LOCATION" in lines[i].upper() and i+1 < len(lines):
                loc = lines[i+1].strip(); break
        return t_id, title, loc, "JKR Sarawak", raw_date

    @staticmethod
    def seb_energy(block, lines, idx):
        id_m = re.search(r'(Doc\d+)', block)
        t_id = id_m.group() if id_m else "Unknown"
        title = get_long_title(lines, idx)
        dates = re.findall(r'(\d{2}/\d{2}/2026)', block)
        raw_date = dates[1] if len(dates) >= 2 else (dates[0] if dates else None)
        return t_id, title, "SEB Area", "Sarawak Energy", raw_date

def check_updates():
    if not os.path.exists(DB_FILE): 
        with open(DB_FILE, 'w', encoding='utf-8') as f: pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={'width': 1366, 'height': 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        for site in SITES:
            page = context.new_page()
            print(f"🔍 Scanning: {site['name']}...")
            try:
                page.goto(site['url'], wait_until="networkidle", timeout=60000)
                
                if site['type'] == "seb":
                    time.sleep(5) 
                    combined_text = ""
                    for frame in page.frames:
                        try:
                            frame.wait_for_load_state("load")
                            content = frame.inner_text("body")
                            if site['id_tag'] in content:
                                combined_text += content + "\n"
                        except: continue
                elif site['type'] == "table":
                    page.wait_for_timeout(3000)
                    rows = page.query_selector_all("table tr")
                    for row in rows:
                        cells = row.query_selector_all("td")
                        if len(cells) < 6: continue
                        t_id = cells[2].inner_text().strip()
                        raw_date = cells[5].inner_text()
                        is_2026, final_date = validate_and_filter_2026(raw_date)
                        ukey = f"KKDW_{t_id}"
                        if is_2026 and not is_duplicate(ukey):
                            send_alert(site['name'], t_id, cells[1].inner_text().strip(), cells[0].inner_text().strip(), "KKDW", final_date, site['url'])
                            save_to_db(ukey)
                    continue
                else:
                    page.wait_for_timeout(3000)
                    combined_text = page.inner_text("body")

                lines = [l.strip() for l in combined_text.split("\n") if l.strip()]
                for i in range(len(lines)):
                    if site['id_tag'] in lines[i]:
                        block = " ".join(lines[i : min(len(lines), i+20)])
                        if "JBALB" in site['name']: res = SiteParser.jbalb_sarawak(block, lines, i)
                        elif "JKR" in site['name']: res = SiteParser.jkr_sarawak(block, lines, i)
                        elif "SEB" in site['name']: res = SiteParser.seb_energy(block, lines, i)
                        elif "RECODA" in site['name']:
                            id_m = re.search(r'(RCDA/T/[A-Z0-9/]+)', block)
                            t_id = id_m.group() if id_m else "Unknown"
                            title = get_long_title(lines, i)
                            raw_date = smart_date_parser(block)
                            res = (t_id, title, "Sarawak", "RECODA", raw_date)
                        else: continue
                        
                        t_id, title, loc, board, raw_date = res
                        is_2026, final_date = validate_and_filter_2026(raw_date)
                        ukey = f"{site['name'].split()[0]}_{t_id}".replace(" ", "")
                        
                        if is_2026 and not is_duplicate(ukey) and t_id != "Unknown":
                            send_alert(site['name'], t_id, title, loc, board, final_date, site['url'])
                            save_to_db(ukey)
            except Exception as e: print(f"⚠️ {site['name']} Error: {e}")
            finally: page.close()
        browser.close()

if __name__ == "__main__":
    check_updates()