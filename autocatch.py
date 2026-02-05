import os
import time
import requests
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- CORE CONFIGURATION ---
TELEGRAM_TOKEN = "8249171192:AAGEjyCYuF2_EqrIa6cLRIWkIuSuB0co7VY"
TELEGRAM_CHAT_ID = "5101247595" 
DB_FILE = "seen_projects.txt"
# Filter tenders older than Oct 1st, 2025
CUTOFF_DATE = datetime(2025, 10, 1)

# Search Keywords for filtering relevant tenders
KEYWORDS = ["KUCHING", "SARAWAK", "ROAD", "INFRASTRUCTURE", "LPS", "SRI AMAN", "BINTULU", "ELECTRICAL", "CABLE", "POLE", "WATER", "PIPELINE"]

# Target Portals Configuration
SITES = [
    {"name": "JKR Sarawak", "url": "https://jkr.sarawak.gov.my/web/subpage/tender_and_quotation_list/tender", "id_tag": "T/", "type": "text"},
    {"name": "RECODA Sarawak", "url": "https://recoda.gov.my/tender/", "id_tag": "RCDA/", "type": "text"},
    {"name": "SEB (Sarawak Energy)", "url": "https://os.sarawakenergy.com.my/etender/", "id_tag": "Doc", "type": "text"},
    {"name": "JBALB Sarawak", "url": "https://jbalb.sarawak.gov.my/web/subpage/webpage_view/89", "id_tag": "T/JBALB/", "type": "text"},
    {"name": "Sacofa", "url": "https://www.sacofa.com.my/index.php/procurement", "id_tag": "Closing Date", "type": "text"},
    {"name": "KKDW (Rural Link)", "url": "https://www.rurallink.gov.my/tender-sebut-harga/iklan-tawaran-tender/", "id_tag": "KKDW", "type": "table"}
]

# --- SYSTEM NOTIFICATION FUNCTIONS ---
def send_status_report(msg_type, total_found=0):
    """Sends initialization and completion heartbeats to Telegram"""
    if msg_type == "START":
        text = (
            f"🚀 *Autocatch System Initialized*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚙️ Status: System Functional\n"
            f"🏃 Action: Commencing Weekly Scanning...\n"
            f"⏰ Time: `{time.ctime()}`"
        )
    else:
        text = (
            f"🏁 *Weekly Scanning Report*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Result: Found *{total_found}* new tender(s)\n"
            f"📅 Filter: Excluded records before {CUTOFF_DATE.strftime('%Y-%m-%d')}\n"
            f"💤 Status: Task finished. Entering standby mode."
        )
    
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=15)
    except: pass

# --- PARSING & UTILITY FUNCTIONS ---
def parse_date(date_str):
    """Standardizes various date formats for comparison"""
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
    """Extracts tender details from unstructured text-based websites"""
    t_id, loc, board, closing = "Unknown", "N/A", "N/A", "Check Website"
    
    id_match = re.search(r'([A-Z0-9]+/[A-Z0-9/.]+|Doc\d+)', text)
    if id_match: t_id = id_match.group()

    if "Sacofa" in site_name and all_lines:
        board = "Sacofa Sdn Bhd"
        # Regex to isolate date from phone numbers/contact info
        date_match = re.search(r'Closing Date.*?(\d{1,2}/\d{1,2}/\d{4})', text, re.I)
        closing = date_match.group(1) if date_match else "Check Website"
        # Backtrack to find the actual project title for Sacofa
        for j in range(current_idx - 1, max(-1, current_idx - 15), -1):
            line = all_lines[j].strip()
            if "SACOFA" in line.upper() and len(line) > 15 and "COPYRIGHT" not in line.upper():
                t_id = line
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
    
    return t_id, loc, board, closing

def send_alert(site_name, t_id, loc, board, closing, url):
    """Sends a formatted alert for a newly discovered tender"""
    message = (
        f"📢 *NEW TENDER DISCOVERED: {site_name}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 *Ref:* `{t_id}`\n"
        f"📍 *Location:* {loc}\n"
        f"🏛️ *Authority:* {board}\n"
        f"📅 *Deadline:* {closing}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔗 [Open Official Portal]({url})"
    )
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=15)
    except: pass

# --- MAIN CRAWLER LOGIC ---
def check_updates():
    send_status_report("START")
    print(f"--- 🛡️ Full Site Scanning Started [{time.ctime()}] ---")
    
    if not os.path.exists(DB_FILE): open(DB_FILE, 'w').close()
    with open(DB_FILE, 'r', encoding='utf-8') as f: seen = set(f.read().splitlines())

    overall_new_found = 0

    with sync_playwright() as p:
        for site in SITES:
            # SEB & Sacofa usually require visual scrolling for dynamic loading
            is_visible = any(x in site['name'] for x in ["SEB", "Sacofa"])
            print(f"\n🔍 Scanning: {site['name']}...")
            
            browser = p.chromium.launch(headless=(not is_visible)) 
            
            # Updated context with a larger window size (1920x1080)
            context = browser.new_context(
                viewport={'width': 50, 'height': 50},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            try:
                if site['type'] == "table":
                    # --- TABLE-BASED EXTRACTION (e.g., KKDW) ---
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
                            send_alert(site['name'], t_id, loc, "KKDW (Rural Link)", closing, site['url'])
                            with open(DB_FILE, 'a', encoding='utf-8') as f:
                                f.write(ukey + "\n")
                                f.flush(); os.fsync(f.fileno())
                            seen.add(ukey); overall_new_found += 1
                else:
                    # --- TEXT-BASED EXTRACTION (e.g., JKR, Sacofa) ---
                    if "SEB" in site['name']:
                        page.goto(site['url'], wait_until="commit", timeout=90000)
                        time.sleep(5); page.mouse.wheel(0, 500)
                    elif "Sacofa" in site['name']:
                        page.goto(site['url'], wait_until="networkidle", timeout=60000)
                        page.evaluate("window.scrollTo(0, 800)"); time.sleep(4)
                    else:
                        page.goto(site['url'], wait_until="networkidle", timeout=60000)
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
                            # Exclude old records by ID year for JBALB
                            if "JBALB" in site['name'] and any(y in lines[i] for y in ["2024", "2023"]): continue
                            block = " ".join(lines[i : i + 15])
                            t_id, loc, board, closing = parse_text_details(block, site['name'], lines, i)
                            if t_id == "Unknown": continue
                            ukey = f"{site['name']}_{t_id}"
                            if ukey not in seen:
                                # Apply Date & Keyword Filters
                                closing_dt = parse_date(closing)
                                if closing_dt and closing_dt < CUTOFF_DATE: continue
                                context_block = " ".join(lines[max(0, i-5) : i+10])
                                if not any(k.upper() in context_block.upper() for k in KEYWORDS) and \
                                   not any(x in site['name'] for x in ["SEB", "JBALB", "Sacofa"]): continue

                                send_alert(site['name'], t_id, loc, board, closing, site['url'])
                                with open(DB_FILE, 'a', encoding='utf-8') as f:
                                    f.write(ukey + "\n")
                                    f.flush(); os.fsync(f.fileno())
                                seen.add(ukey); overall_new_found += 1

            except Exception as e: print(f"   ⚠️ Error on {site['name']}: {e}")
            finally: page.close(); browser.close()

    # --- FINAL REPORT ---
    send_status_report("FINISH", overall_new_found)
    print(f"\n--- All Scans Finished [{time.ctime()}] ---")

if __name__ == "__main__":
    check_updates()