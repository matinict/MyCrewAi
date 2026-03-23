# 1. Install dependencies from your pyproject.toml
# uv sync

# 2. Install the Playwright browser binaries (e.g., Chromium)
# uv run playwright install chromium

# 3. Run your Playwright script
# uv run python playwrightScraping.py

# playwrightScraping.py - PRODUCTION VERSION for PlayOwnAi
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import json
import os
import re
from datetime import datetime
import time
import sys

# ==================== CONFIGURATION ====================
URL = "https://socialblade.com/youtube/handle/playownai"
CHANNEL_NAME = "PlayOwnAi"
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==================== HELPER FUNCTIONS ====================
def clean_number(text):
    """Remove commas, spaces, and non-numeric chars, return integer"""
    if not text:
        return 0
    cleaned = re.sub(r'[^\d]', '', str(text).strip())
    return int(cleaned) if cleaned else 0

def extract_after_label(body_text, label, pattern=r'([\d\.\,KMB\$\-]+)'):
    """Extract value after a label, handling newlines and whitespace"""
    regex = rf"{re.escape(label)}\s*[\n\r\s]*({pattern})"
    match = re.search(regex, body_text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else None

def extract_earnings(body_text, period):
    """Extract earnings like '$0 - $5'"""
    pattern = rf"(\$\d+\s*-\s*\$\d+)\s*{re.escape(period)}"
    match = re.search(pattern, body_text, re.IGNORECASE)
    return match.group(1) if match else "N/A"

# ==================== MAIN EXTRACTION ====================
def extract_metrics(page):
    """Extract comprehensive metrics from Social Blade"""
    try:
        page.wait_for_selector("body", state="visible")
        page.wait_for_timeout(5000)
        body_text = page.locator("body").inner_text()
        
        metrics = {}
        
        # --- Basic Metrics ---
        metrics["subscribers"] = clean_number(extract_after_label(body_text, "Subscribers", r'[\d,]+'))
        metrics["views"] = clean_number(extract_after_label(body_text, "Views", r'[\d,]+'))
        metrics["videos"] = clean_number(extract_after_label(body_text, "Videos", r'[\d,]+'))
        
        # --- Channel Info ---
        created = re.search(r"Created On\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", body_text, re.IGNORECASE)
        metrics["created_on"] = created.group(1) if created else "Unknown"
        
        # --- Grade (C-, B+, etc.) ---
        grade = re.search(r"([A-D][\+\-]?)\s*Grade", body_text, re.IGNORECASE)
        metrics["grade"] = grade.group(1) if grade else "N/A"
        
        # --- Ranks ---
        metrics["sb_rank"] = clean_number(extract_after_label(body_text, "SB Rank", r'[\d,]+'))
        metrics["subscribers_rank"] = clean_number(extract_after_label(body_text, "Subscribers Rank", r'[\d,]+'))
        metrics["views_rank"] = clean_number(extract_after_label(body_text, "Views Rank", r'[\d,]+'))
        metrics["bd_rank"] = clean_number(extract_after_label(body_text, "BD Rank", r'[\d,]+'))
        
        # --- 30-Day Growth ---
        subs_30 = extract_after_label(body_text, "Subscribers for the last 30 days", r'\d+')
        metrics["subs_last_30d"] = clean_number(subs_30) if subs_30 else 0
        
        views_30 = extract_after_label(body_text, "Views for the last 30 days", r'[\d\.]+[KMB]?')
        metrics["views_last_30d"] = views_30 if views_30 else "0"
        
        # --- Earnings ---
        metrics["estimated_monthly_earnings"] = extract_earnings(body_text, "Monthly Estimated Earnings")
        metrics["estimated_yearly_earnings"] = extract_earnings(body_text, "Yearly Estimated Earnings")
        
        # --- Daily Metrics Table ---
        daily_metrics = []
        # Pattern: DayYYYY-MM-DD  newSubs  totalSubs  newViews  totalViews  newVids  totalVids  earnings
        daily_pattern = r'([A-Za-z]{3})(\d{4}-\d{2}-\d{2})\s+([\d\-]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+(\d+)\s+([\d,]+)\s+(\$\d+\s*-\s*\$\d+)'
        matches = re.findall(daily_pattern, body_text, re.MULTILINE)
        
        for m in matches:
            daily_metrics.append({
                "day": m[0], "date": m[1],
                "new_subscribers": clean_number(m[2]),
                "total_subscribers": clean_number(m[3]),
                "new_views": clean_number(m[4]),
                "total_views": clean_number(m[5]),
                "new_videos": clean_number(m[6]),
                "total_videos": clean_number(m[7]),
                "estimated_earnings": m[8]
            })
        metrics["daily_metrics"] = daily_metrics[:14]
        
        return metrics
        
    except Exception as e:
        print(f"⚠️ Extraction Error: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

# ==================== MAIN ====================
def main(max_retries=3):
    print("=" * 70, flush=True)
    print(f"🎯 PlayOwnAi Social Blade Scraper", flush=True)
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"🎯 Mission: Automate smarter with AI - less code, no face, just power", flush=True)
    print("=" * 70, flush=True)
    
    for attempt in range(1, max_retries + 1):
        print(f"\n🔄 Attempt {attempt}/{max_retries}", flush=True)
        
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
                )
                
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    timezone_id="Asia/Dhaka"
                )
                
                page = context.new_page()
                stealth = Stealth()
                stealth.apply_stealth_sync(page)
                
                print(f"🌐 Navigating to: {URL}", flush=True)
                page.goto(URL, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_selector("body", state="visible")
                page.wait_for_timeout(5000)
                
                print("✅ Page loaded", flush=True)
                print(f"📊 Extracting metrics...", flush=True)
                metrics = extract_metrics(page)
                
                # Build final data structure
                data = {
                    "timestamp": datetime.now().isoformat(),
                    "channel": CHANNEL_NAME,
                    "url": URL,
                    "channel_info": {
                        "founder": "Abdul Matin",
                        "mission": "Automate smarter with AI - less code, no face, just power",
                        "business_lines": ["YouTube Education Channel", "AI Call Center Product (R&D)", "CrewAI Projects"],
                        "location": "Bangladesh",
                        "goals": ["Teach AI automation", "Empower freelancers", "Help viewers launch AI"]
                    },
                    "metrics": metrics,
                    "status": "success" if "error" not in metrics else "partial"
                }
                
                # Save JSON
                file_path = f"{OUTPUT_DIR}/socialblade_structured_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                print(f"✅ Saved: {file_path}", flush=True)
                
                # Print dashboard
                print("\n" + "=" * 70, flush=True)
                print("📈 PLAYOWNAI CHANNEL DASHBOARD", flush=True)
                print("=" * 70, flush=True)
                m = metrics
                print(f"👥 Subscribers:        {m.get('subscribers', 'N/A'):,}", flush=True)
                print(f"👁️ Total Views:         {m.get('views', 'N/A'):,}", flush=True)
                print(f"🎬 Total Videos:        {m.get('videos', 'N/A')}", flush=True)
                print(f"🏆 Grade:               {m.get('grade', 'N/A')}", flush=True)
                print(f"🌍 SB Rank:             #{m.get('sb_rank', 'N/A'):,}", flush=True)
                print(f"🇧🇩 BD Rank:             #{m.get('bd_rank', 'N/A'):,}", flush=True)
                print(f"📈 Subs (30d):          +{m.get('subs_last_30d', 'N/A')}", flush=True)
                print(f"📈 Views (30d):         {m.get('views_last_30d', 'N/A')}", flush=True)
                print(f"💰 Est. Monthly:        {m.get('estimated_monthly_earnings', 'N/A')}", flush=True)
                print(f"💰 Est. Yearly:         {m.get('estimated_yearly_earnings', 'N/A')}", flush=True)
                print(f"📊 Daily Records:       {len(m.get('daily_metrics', []))} days", flush=True)
                print("=" * 70, flush=True)
                
                # Recent activity
                if m.get('daily_metrics'):
                    print("\n📅 RECENT ACTIVITY:", flush=True)
                    for day in m['daily_metrics'][-3:]:
                        print(f"  {day['date']}: +{day['new_subscribers']} subs, {day['new_views']:,} views, {day['estimated_earnings']}", flush=True)
                    print("=" * 70, flush=True)
                
                browser.close()
                print("🔒 Browser closed", flush=True)
                return data
                
            except Exception as e:
                print(f"❌ Attempt {attempt} failed: {e}", flush=True, file=sys.stderr)
                error_data = {"timestamp": datetime.now().isoformat(), "channel": CHANNEL_NAME, "attempt": attempt, "error": str(e), "status": "failed"}
                error_path = f"{OUTPUT_DIR}/error_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                with open(error_path, "w", encoding="utf-8") as f:
                    json.dump(error_data, f, indent=2)
                
                if attempt < max_retries:
                    print(f"⏳ Retrying in 10s...", flush=True)
                    time.sleep(10)
                else:
                    print(f"⚠️ All attempts failed. Log: {error_path}", flush=True)
            
            finally:
                try:
                    browser.close()
                except:
                    pass
    return None

if __name__ == "__main__":
    main()