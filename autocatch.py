import os
import time
import requests
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- 核心配置 ---
TELEGRAM_TOKEN = "8249171192:AAGEjyCYuF2_EqrIa6cLRIWkIuSuB0co7VY"
TELEGRAM_CHAT_ID = "5101247595" 
DB_FILE = "seen_projects.txt"
# 设定截止日期：只抓取 2025年10月1日 之后的标讯
CUTOFF_DATE = datetime(2025, 10, 1)

KEYWORDS = ["KUCHING", "SARAWAK", "ROAD", "INFRASTRUCTURE", "LPS", "SRI AMAN", "BINTULU", "ELECTRICAL", "CABLE", "POLE", "WATER", "PIPELINE"]

SITES = [
    {"name": "JKR Sarawak", "url": "https://jkr.sarawak.gov.my/web/subpage/tender_and_quotation_list/tender", "id_tag": "T/"},
    {"name": "RECODA Sarawak", "url": "https://recoda.gov.my/tender/", "id_tag": "RCDA/"},
    {"name": "SEB (Sarawak Energy)", "url": "https://os.sarawakenergy.com.my/etender/", "id_tag": "Doc"},
    {"name": "JBALB Sarawak", "url": "https://jbalb.sarawak.gov.my/web/subpage/webpage_view/89", "id_tag": "T/JBALB/"},
    {"name": "Sacofa", "url": "https://www.sacofa.com.my/index.php/procurement", "id_tag": "Closing Date"}
]

# --- 工具函数 ---
def parse_date(date_str):
    if not date_str: return None
    try:
        # 增强解析：处理 JBALB 的 "JAN.2025" 这种缩写
        clean_date = date_str.replace(".", " ").upper().strip()
        clean_date = re.sub(r'(\d+)(ST|ND|RD|TH)', r'\1', clean_date)
        
        formats = ("%d %b %Y", "%d %B %Y", "%b %Y", "%B %Y", "%d/%m/%Y", "%d-%m-%Y")
        for fmt in formats:
            try:
                dt = datetime.strptime(clean_date, fmt)
                # 如果只有月份和年份（如 JAN 2025），自动补全为该月 1 号
                return dt
            except:
                continue
    except:
        pass
    return None

def parse_details(text, site_name, all_lines=None, current_idx=None):
    t_id, loc, board, closing = "Unknown", "N/A", "N/A", "Check Website"
    
    if "Sacofa" in site_name and all_lines is not None:
        board = "Sacofa Sdn Bhd"
        closing = text.split(":")[-1].strip() if ":" in text else "Check Website"
        # 向上回溯找标题
        for j in range(current_idx - 1, max(-1, current_idx - 15), -1):
            line = all_lines[j].strip()
            if "SACOFA" in line.upper() and len(line) > 15 and "COPYRIGHT" not in line.upper():
                t_id = line
                break
        loc = "Telecommunication Infra"
        return t_id, loc, board, closing

    id_match = re.search(r'([A-Z0-9]+/[A-Z0-9/.]+|Doc\d+)', text)
    if id_match: t_id = id_match.group()

    if "JBALB" in site_name:
        board = "JBALB Sarawak"
        if "Closing Date:" in text:
            parts = text.split("Closing Date:")
            closing = parts[1].split("\n")[0].split("Document")[0].strip()
            if "At " in parts[0]: loc = parts[0].split("At ")[1].split(",")[0].strip()
    elif "JKR" in site_name:
        board = "LPS / JKR Sarawak"
        if "Project Location" in text: loc = text.split("Project Location")[1].split("Tender Board")[0].replace(":", "").strip()
        if "Closing Date/Time" in text: closing = text.split("Closing Date/Time")[1].split("Doc. Fee")[0].replace(":", "").strip()
    elif "RECODA" in site_name:
        board = "RECODA Sarawak"
        date_pattern = re.search(r'(\d{1,2}\s+[A-Za-z]+\s+\d{4})', text)
        if date_pattern: closing = date_pattern.group(1)
    elif "SEB" in site_name:
        board = "Sarawak Energy"
        dates = re.findall(r'\d{2}/\d{2}/\d{4}', text)
        if dates: closing = dates[-1]
        parts = text.split(t_id)
        if len(parts) > 1: loc = parts[1][:70].strip().split("\n")[0] + "..."
    
    return t_id, loc, board, closing

def send_alert(site_name, t_id, loc, board, closing, url):
    message = (
        f"📢 *NEW TENDER: {site_name}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 *Ref:* `{t_id}`\n"
        f"📍 *Loc:* {loc}\n"
        f"🏛️ *Board:* {board}\n"
        f"📅 *Deadline:* {closing}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔗 [Open Link]({url})"
    )
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=15)
    except: pass

def check_updates():
    print(f"--- 🛡️ Full Site Scanning Started [{time.ctime()}] ---")
    if not os.path.exists(DB_FILE): open(DB_FILE, 'w').close()
    with open(DB_FILE, 'r', encoding='utf-8') as f: seen = set(f.read().splitlines())

    with sync_playwright() as p:
        for site in SITES:
            is_visible = any(x in site['name'] for x in ["SEB", "Sacofa"])
            print(f"\n🔍 Scanning: {site['name']}...")
            
            browser = p.chromium.launch(headless=(not is_visible)) 
            context = browser.new_context(viewport={'width': 1280, 'height': 800})
            page = context.new_page()
            
            try:
                if "SEB" in site['name']:
                    page.goto(site['url'], wait_until="commit", timeout=90000)
                    time.sleep(5)
                    page.mouse.wheel(0, 500)
                    time.sleep(2)
                elif "Sacofa" in site['name']:
                    page.goto(site['url'], wait_until="networkidle", timeout=60000)
                    page.evaluate("window.scrollTo(0, 800)")
                    time.sleep(4)
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
                found_on_site = 0
                
                for i in range(len(lines)):
                    if site['id_tag'] in lines[i]:
                        # 修正：根据 JBALB 的 ID 进行初步年份过滤
                        if "JBALB" in site['name'] and any(y in lines[i] for y in ["2024", "2023"]): continue
                        
                        t_id, loc, board, closing = parse_details(lines[i], site['name'], lines, i)
                        if t_id == "Unknown": continue
                        
                        ukey = f"{site['name']}_{t_id}"
                        if ukey in seen: continue
                        
                        # 日期过滤逻辑
                        closing_dt = parse_date(closing)
                        # 如果是 JBALB ID 里的日期缩写，我们也要解析它
                        id_date = parse_date(lines[i].split("/")[-1]) if "JBALB" in site['name'] else None
                        
                        # 只要解析出的日期早于截止日期，就跳过
                        if (closing_dt and closing_dt < CUTOFF_DATE) or (id_date and id_date < CUTOFF_DATE):
                            continue

                        # 关键词过滤逻辑
                        context_block = " ".join(lines[max(0, i-5) : i+10])
                        if not any(k.upper() in context_block.upper() for k in KEYWORDS) and \
                           not any(x in site['name'] for x in ["SEB", "JBALB", "Sacofa"]):
                            continue

                        send_alert(site['name'], t_id, loc, board, closing, site['url'])
                        
                        # 💡 强化写入逻辑：确保立刻存盘
                        with open(DB_FILE, 'a', encoding='utf-8') as f:
                            f.write(ukey + "\n")
                            f.flush()
                            os.fsync(f.fileno())
                        
                        seen.add(ukey)
                        found_on_site += 1
                        print(f"   ✅ Found: {t_id}")

                print(f"   📊 {site['name']} 完成，新增 {found_on_site} 条。")

            except Exception as e:
                print(f"   ⚠️ Error on {site['name']}: {e}")
            finally:
                page.close()
                browser.close()

    print(f"\n--- All Scans Finished [{time.ctime()}] ---")

if __name__ == "__main__":
    check_updates()