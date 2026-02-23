import os
import time
import requests
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- 配置区 ---
TELEGRAM_TOKEN = "8249171192:AAGEjyCYuF2_EqrIa6cLRIWkIuSuB0co7VY"
USER_IDS = ["5101247595", "7763852448"] 
DB_FILE = "seen_projects.txt"

SITES = [
    {"name": "JKR Sarawak", "url": "https://jkr.sarawak.gov.my/web/subpage/tender_and_quotation_list/tender", "id_tag": "T/", "type": "text"},
    {"name": "RECODA Sarawak", "url": "https://recoda.gov.my/tender/", "id_tag": "RCDA/", "type": "text"},
    {"name": "SEB (Sarawak Energy)", "url": "https://os.sarawakenergy.com.my/etender/", "id_tag": "Doc", "type": "text"},
    {"name": "JBALB Sarawak", "url": "https://jbalb.sarawak.gov.my/web/subpage/webpage_view/89", "id_tag": "T/JBALB/", "type": "text"},
    {"name": "Sacofa", "url": "https://www.sacofa.com.my/index.php/archived-tender-notice", "id_tag": "Reference Number", "type": "text"},
    {"name": "KKDW (Rural Link)", "url": "https://www.rurallink.gov.my/tender-sebut-harga/iklan-tawaran-tender/", "id_tag": "KKDW", "type": "table"}
]

# --- 核心解析工具 ---
def smart_date_parser(text):
    if not text: return "Refer Portal"
    # 扩展马来文月份映射，确保长日期能转成数字格式
    month_map = {
        "JANUARI": "01", "FEBRUARI": "02", "MAC": "03", "APRIL": "04", 
        "MEI": "05", "JUN": "06", "JULAI": "07", "OGOS": "08", 
        "SEPTEMBER": "09", "OKTOBER": "10", "NOVEMBER": "11", "DISEMBER": "12"
    }
    clean_text = text.upper()
    
    # 1. 尝试匹配标准数字格式 DD/MM/YYYY
    standard = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{4})', clean_text)
    if standard: return standard.group(1)
    
    # 2. 尝试匹配马来文长格式 (例如 24 FEBRUARI 2026)
    # 增加对这种排版的兼容性
    verbose_pattern = r'(\d{1,2})\s+(JANUARI|FEBRUARI|MAC|APRIL|MEI|JUN|JULAI|OGOS|SEPTEMBER|OKTOBER|NOVEMBER|DISEMBER)\s+(\d{4})'
    verbose_match = re.search(verbose_pattern, clean_text)
    if verbose_match:
        d, m_name, y = verbose_match.groups()
        m = month_map.get(m_name, "01")
        return f"{d.zfill(2)}-{m}-{y}"
        
    return "Refer Portal"

class SiteParser:
    @staticmethod
    def jkr_sarawak(block, lines, idx):
        id_match = re.search(r'(T/\d+/\d+/\d+)', block)
        t_id = id_match.group() if id_match else "Unknown"
        candidates = []
        for line in lines[max(0, idx-1) : min(len(lines), idx+10)]:
            l = line.strip()
            if len(l) < 20 or any(n in l.upper() for n in ["SPECIALIZATION", "CLASS", "RM", "TENDER BOARD"]): continue
            score = len(l)
            if any(w in l.upper() for w in ["PEMBINAAN", "MENYIAPKAN", "CADANGAN", "KERJA", "PROPOSED", "PROJECT"]): score += 100
            candidates.append((score, l))
        title = sorted(candidates, key=lambda x: x[0], reverse=True)[0][1] if candidates else "N/A"
        closing_part = re.search(r'Closing Date.*?(?:\d{4})', block, re.S | re.I)
        closing = smart_date_parser(closing_part.group() if closing_part else block)
        loc = "Check Portal"
        for i in range(idx, min(len(lines), idx+10)):
            if "PROJECT LOCATION" in lines[i].upper() and i+1 < len(lines):
                loc = lines[i+1].strip(); break
        return t_id, title, loc, "JKR Sarawak", closing

    @staticmethod
    def jbalb_sarawak(block, lines, idx):
        id_match = re.search(r'(T/JBALB/\d+/[A-Z.]+.\d+)', block)
        t_id = id_match.group() if id_match else "Unknown"
        title = lines[idx+1].strip() if len(lines) > idx+1 else "N/A"
        date_block = re.search(r'Closing Date[:\s]+(.*?)(?=Document Fee|$)', block, re.I | re.S)
        closing = smart_date_parser(date_block.group(1)) if date_block else "Refer Portal"
        return t_id, title, "Water Supply", "JBALB Sarawak", closing

    @staticmethod
    def sacofa_new(block, lines, idx):
        id_match = re.search(r'Reference Number\s*:\s*([\w\-/.]+)', block, re.I)
        t_id = id_match.group(1) if id_match else "Unknown"
        title = "N/A"
        for j in range(idx-1, max(-1, idx-5), -1):
            if len(lines[j]) > 20: title = lines[j].strip(); break
        closing = "Refer Portal"
        closing_match = re.search(r'Closing Date\s*[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{4})', block, re.I)
        if closing_match: closing = closing_match.group(1)
        return t_id, title, "Telecomm", "Sacofa", closing

def send_alert(site_name, t_id, title, loc, board, closing, url):
    message = f"📢 *NEW TENDER: {site_name}*\n━━━━━━━━━━━━━━━\n📋 *Project:* `{title}`\n\n🆔 *Ref:* `{t_id}`\n📍 *Loc:* {loc}\n🏛️ *Dept:* {board}\n📅 *Due:* {closing}\n━━━━━━━━━━━━━━━\n🔗 [Open Official Portal]({url})"
    for user in USER_IDS:
        api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try: requests.post(api, data={"chat_id": user, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=15)
        except: pass

def check_updates():
    if not os.path.exists(DB_FILE): open(DB_FILE, 'w').close()
    with open(DB_FILE, 'r', encoding='utf-8') as f: seen = set(f.read().splitlines())

    with sync_playwright() as p:
        browser_silent = p.chromium.launch(headless=True)
        browser_visible = p.chromium.launch(headless=False)
        
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        context_silent = browser_silent.new_context(viewport={'width': 180, 'height': 80}, user_agent=ua)
        context_visible = browser_visible.new_context(viewport={'width': 180, 'height': 80}, user_agent=ua)

        for site in SITES:
            if "SEB" in site['name']:
                page = context_visible.new_page()
            else:
                page = context_silent.new_page()
            
            print(f" Scanning: {site['name']}...")

            try:
                page.goto(site['url'], wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)

                if site['type'] == "table":
                    rows = page.query_selector_all("table tr")
                    for row in rows:
                        cells = row.query_selector_all("td")
                        if len(cells) < 6: continue
                        t_id = cells[2].inner_text().strip()
                        ukey = f"KKDW_{t_id}"
                        if ukey not in seen and t_id != "-":
                            send_alert(site['name'], t_id, cells[1].inner_text().strip(), f"{cells[0].inner_text().strip()} - Rural", "KKDW", smart_date_parser(cells[5].inner_text()), site['url'])
                            with open(DB_FILE, 'a') as f: f.write(ukey + "\n")
                            seen.add(ukey)
                else:
                    combined_text = ""
                    for frame in page.frames:
                        try: combined_text += frame.inner_text("body") + "\n"
                        except: continue
                    lines = [l.strip() for l in combined_text.split("\n") if l.strip()]
                    
                    for i in range(len(lines)):
                        if site['id_tag'] in lines[i]:
                            # --- 关键改进点：扩大 RECODA 的搜索块 ---
                            block = " ".join(lines[max(0, i-2) : min(len(lines), i+20)])
                            
                            if "JKR" in site['name']: res = SiteParser.jkr_sarawak(block, lines, i)
                            elif "JBALB" in site['name']: res = SiteParser.jbalb_sarawak(block, lines, i)
                            elif "Sacofa" in site['name']: res = SiteParser.sacofa_new(block, lines, i)
                            elif "RECODA" in site['name']:
                                # 优化 RECODA 匹配逻辑
                                id_m = re.search(r'(RCDA/[A-Z0-9/]+)', block)
                                t_id = id_m.group() if id_m else "Unknown"
                                title = lines[i+1] if i+1 < len(lines) else "N/A"
                                # 使用增强后的日期解析器
                                closing = smart_date_parser(block)
                                res = (t_id, title, "Sarawak", "RECODA", closing)
                            elif "SEB" in site['name']:
                                id_m = re.search(r'(Doc\d+)', block)
                                t_id = id_m.group() if id_m else "Unknown"
                                title = lines[i+1] if i+1 < len(lines) else "See Description"
                                res = (t_id, title, "SEB Area", "Sarawak Energy", smart_date_parser(block))
                            else: continue
                            
                            t_id, title, loc, board, closing = res
                            ukey = f"{site['name']}_{t_id}"
                            if ukey not in seen and t_id != "Unknown":
                                send_alert(site['name'], t_id, title, loc, board, closing, site['url'])
                                with open(DB_FILE, 'a') as f: f.write(ukey + "\n")
                                seen.add(ukey)
            except Exception as e: print(f"⚠️ {site['name']} Error: {e}")
            finally: page.close()
        
        browser_silent.close()
        browser_visible.close()

if __name__ == "__main__":
    check_updates()