import os
import time
import requests
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- CORE CONFIGURATION ---
TELEGRAM_TOKEN = "8249171192:AAGEjyCYuF2_EqrIa6cLRIWkIuSuB0co7VY"
USER_IDS = ["5101247595"] 
DB_FILE = "seen_projects.txt"
CUTOFF_DATE = datetime(2025, 10, 1)

KEYWORDS = ["KUCHING", "SARAWAK", "ROAD", "INFRASTRUCTURE", "LPS", "SRI AMAN", "BINTULU", "ELECTRICAL", "CABLE", "POLE", "WATER", "PIPELINE"]

SITES = [
    {"name": "JKR Sarawak", "url": "https://jkr.sarawak.gov.my/web/subpage/tender_and_quotation_list/tender", "id_tag": "T/", "type": "text"},
    {"name": "RECODA Sarawak", "url": "https://recoda.gov.my/tender/", "id_tag": "RCDA/", "type": "text"},
    {"name": "SEB (Sarawak Energy)", "url": "https://os.sarawakenergy.com.my/etender/", "id_tag": "Doc", "type": "text"},
    {"name": "JBALB Sarawak", "url": "https://jbalb.sarawak.gov.my/web/subpage/webpage_view/89", "id_tag": "T/JBALB/", "type": "text"},
    {"name": "Sacofa", "url": "https://www.sacofa.com.my/index.php/procurement", "id_tag": "Closing Date", "type": "text"},
    {"name": "KKDW (Rural Link)", "url": "https://www.rurallink.gov.my/tender-sebut-harga/iklan-tawaran-tender/", "id_tag": "KKDW", "type": "table"}
]

def broadcast(message):
    for chat_id in USER_IDS:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id, 
            "text": message, 
            "parse_mode": "Markdown",
            "disable_web_page_preview": True # 设为 True 让消息更整洁
        }
        try:
            requests.post(url, data=payload, timeout=15)
        except Exception as e:
            print(f"Failed to send message to {chat_id}: {e}")

# --- SYSTEM NOTIFICATION FUNCTIONS ---
def send_status_report(msg_type, total_found=0):
    if msg_type == "START":
        text = (
            f"🚀 *Autocatch System Initialized*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚙️ Status: `Scanning...`"
        )
    else:
        text = (
            f"🏁 *Weekly Scanning Report*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Result: Found *{total_found}* new tender(s)\n"
            f"📅 Filter: Excluded before {CUTOFF_DATE.strftime('%Y-%m-%d')}\n"
            f"💤 Status: `Standby`"
        )
    broadcast(text)

# --- PARSING & UTILITY FUNCTIONS ---
def parse_date(date_str):
    if not date_str or any(x in date_str for x in ["Check", "Refer", "+60"]): return None
    try:
        clean_date = date_str.replace(".", " ").upper().strip()
        clean_date = re.sub(r'(\d+)(ST|ND|RD|TH)', r'\1', clean_date)
        formats = ("%d %b %Y", "%d %B %Y", "%b %Y", "%B %Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")
        for fmt in formats:
            try: return datetime.strptime(clean_date, fmt)
            except: continue
    except: pass
    return None

def parse_text_details(text, site_name, all_lines=None, current_idx=None):
    t_id, title, loc, board, closing = "Unknown", "N/A", "N/A", "N/A", "Check Website"
    
    id_match = re.search(r'([A-Z0-9]+/[A-Z0-9/.]+|Doc\d+)', text)
    if id_match: t_id = id_match.group()

    # --- 新增：尝试从上下文中抓取项目标题 ---
    if all_lines and current_idx is not None:
        # 通常 ID 的上一行就是 Title
        if current_idx > 0:
            potential_title = all_lines[current_idx - 1].strip()
            # 简单判断这行不是日期或太短，就是标题
            if len(potential_title) > 15 and not any(month in potential_title.upper() for month in ["JAN", "FEB", "MAR", "APR", "MAY", "JUN"]):
                title = potential_title

    if "Sacofa" in site_name and all_lines:
        board = "Sacofa Sdn Bhd"
        date_match = re.search(r'Closing Date.*?(\d{1,2}/\d{1,2}/\d{4})', text, re.I)
        closing = date_match.group(1) if date_match else "Check Website"
        for j in range(current_idx - 1, max(-1, current_idx - 15), -1):
            line = all_lines[j].strip()
            if "SACOFA" in line.upper() and len(line) > 15 and "COPYRIGHT" not in line.upper():
                title = line # 原代码把 title 存进了 t_id，这里修正下
                break
        loc = "Telecommunication Infrastructure"
    elif "JBALB" in site_name:
        board = "JBALB Sarawak"
        date_match = re.search(r'(\d{1,2}\s+[A-Z]{3,}\s+\d{4})', text, re.I)
        if date_match: closing = date_match.group()
        loc_match = re.search(r'At\s+([^,\n\d]+)', text)
        if loc_match: loc = loc_match.group(1).strip()
    elif "JKR" in site_name:
        board = "LPS / JKR Sarawak"
        loc_match = re.search(r'Location[:\s]+(.*?)(?=Tender Board|$)', text, re.S | re.I)
        if loc_match: loc = loc_match.group(1).strip().replace("\n", " ")
        date_match = re.search(r'Closing Date.*?[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4})', text, re.I)
        if date_match: closing = date_match.group(1)
    elif "SEB" in site_name:
        board = "Sarawak Energy"
        dates = re.findall(r'\d{2}/\d{2}/\d{4}', text)
        if dates: closing = dates[-1]
        parts = text.split(t_id)
        if len(parts) > 1: loc = parts[1][:70].strip().split("\n")[0] + "..."
    
    return t_id, title, loc, board, closing

def send_alert(site_name, t_id, title, loc, board, closing, url):
    """美化后的 Tender 提醒消息"""
    message = (
        f"📢 *NEW TENDER: {site_name}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📋 *Project:* `{title}`\n\n"
        f"🆔 *Ref:* `{t_id}`\n"
        f"📍 *Loc:* {loc}\n"
        f"🏛️ *Dept:* {board}\n"
        f"📅 *Due:* {closing}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔗 [Open Official Portal]({url})"
    )
    broadcast(message)

# --- MAIN CRAWLER LOGIC ---
def check_updates():
    send_status_report("START")
    if not os.path.exists(DB_FILE): open(DB_FILE, 'w').close()
    with open(DB_FILE, 'r', encoding='utf-8') as f: seen = set(f.read().splitlines())
    overall_new_found = 0

    with sync_playwright() as p:
        for site in SITES:
            is_visible = any(x in site['name'] for x in ["SEB", "Sacofa"])
            print(f"🔍 Scanning: {site['name']}...")
            browser = p.chromium.launch(headless=(not is_visible)) 
            context = browser.new_context(
                viewport={'width': 50, 'height': 80},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            try:
                if site['type'] == "table":
                    page.goto(site['url'], wait_until="networkidle", timeout=90000)
                    page.wait_for_selector("table tr td", timeout=30000)
                    time.sleep(3)
                    rows = page.query_selector_all("table tr")
                    for row in rows:
                        cells = row.query_selector_all("td")
                        if len(cells) < 5: continue
                        loc = cells[0].inner_text().strip()
                        title = cells[1].inner_text().strip().split("\n")[0]
                        t_id = cells[2].inner_text().strip()
                        if not t_id or t_id == "-": continue
                        closing = "Refer to Portal"
                        if len(cells) >= 6:
                            p_date = cells[-2].inner_text().strip()
                            if ":" in p_date or "/" in p_date: closing = p_date
                        ukey = f"KKDW_{t_id}"
                        if ukey not in seen:
                            send_alert(site['name'], t_id, title, loc, "KKDW (Rural Link)", closing, site['url'])
                            with open(DB_FILE, 'a', encoding='utf-8') as f:
                                f.write(ukey + "\n")
                                f.flush(); os.fsync(f.fileno())
                            seen.add(ukey); overall_new_found += 1
                else:
                    page.goto(site['url'], wait_until="networkidle", timeout=60000)
                    if "SEB" in site['name']:
                        time.sleep(5); page.mouse.wheel(0, 500)
                    elif "Sacofa" in site['name']:
                        page.evaluate("window.scrollTo(0, 800)"); time.sleep(4)
                    else:
                        time.sleep(3)

                    combined_text = ""
                    for frame in page.frames:
                        try:
                            f_text = frame.inner_text("body")
                            if f_text: combined_text += f_text + "\n"
                        except: continue
                    
                    lines = [l.strip() for l in combined_text.split("\n") if l.strip()]
                    for i in range(len(lines)):
                        if site['id_tag'] in lines[i]:
                            if "JBALB" in site['name'] and any(y in lines[i] for y in ["2024", "2023"]): continue
                            block = " ".join(lines[i : i + 15])
                            t_id, title, loc, board, closing = parse_text_details(block, site['name'], lines, i)
                            if t_id == "Unknown": continue
                            ukey = f"{site['name']}_{t_id}"
                            if ukey not in seen:
                                closing_dt = parse_date(closing)
                                if closing_dt and closing_dt < CUTOFF_DATE: continue
                                context_block = " ".join(lines[max(0, i-5) : i+10])
                                if not any(k.upper() in context_block.upper() for k in KEYWORDS) and \
                                   not any(x in site['name'] for x in ["SEB", "JBALB", "Sacofa"]): continue

                                send_alert(site['name'], t_id, title, loc, board, closing, site['url'])
                                with open(DB_FILE, 'a', encoding='utf-8') as f:
                                    f.write(ukey + "\n")
                                    f.flush(); os.fsync(f.fileno())
                                seen.add(ukey); overall_new_found += 1

            except Exception as e: print(f"⚠️ Error on {site['name']}: {e}")
            finally: page.close(); browser.close()

    send_status_report("FINISH", overall_new_found)

if __name__ == "__main__":
    check_updates()