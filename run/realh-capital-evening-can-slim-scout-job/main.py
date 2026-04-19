import functions_framework
from google.cloud import firestore
from google import genai
from google.genai import types
import google.auth
import os
import requests
import json
import urllib.request
import logging
import html
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Set up logging
logging.basicConfig(level=logging.INFO)

# Initialize GCP and Firestore clients
_, project_id = google.auth.default()

def get_region():
    try:
        url = "http://metadata.google.internal/computeMetadata/v1/instance/region"
        headers = {"Metadata-Flavor": "Google"}
        response = requests.get(url, headers=headers, timeout=2)
        if response.status_code == 200:
            return response.text.split('/')[-1]
    except Exception as e:
        logging.warning(f"Metadata server unreachable, using env: {e}")
    return os.environ.get("CLOUD_RUN_REGION", "us-central1")

db_id = os.environ.get("FIRESTORE_DB_ID", "(default)")
db = firestore.Client(project=project_id, database=db_id)

client = genai.Client(
    vertexai=True, 
    project=project_id, 
    location=get_region()
)

def send_telegram_notification(text, is_debug=False):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return

    header = "<b>🧪 DEBUG LOG</b>" if is_debug else "<b>🚀 Evening Scout Complete</b>"
    
    # TRUNCATE SAFETY: Keep under 4000 characters to stay safe from the 4096 limit
    full_text = f"{header}\n\n{text}"
    if len(full_text) > 4000:
        full_text = full_text[:3990] + "\n\n<i>[Message Truncated...]</i>"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": full_text, "parse_mode": "HTML"}
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        error_info = e.read().decode('utf-8')
        logging.error(f"Telegram 400 Error Info: {error_info}")
        # FALLBACK: If HTML fails, send as plain text so you at least get the data
        fallback_payload = {"chat_id": chat_id, "text": f"⚠️ HTML Parse Failed - Sending Plain:\n\n{text[:3500]}"}
        fallback_data = json.dumps(fallback_payload).encode('utf-8')
        fallback_req = urllib.request.Request(url, data=fallback_data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(fallback_req)

def get_portfolio_tickers():
    """Fetches the current portfolio holdings from Firestore."""
    tickers = []
    try:
        docs = db.collection('portfolio').stream()
        for doc in docs:
            tickers.append(doc.id)
        return tickers
    except Exception as e:
        logging.error(f"Failed to fetch portfolio tickers: {e}")
        return []

def clear_collection(coll_ref):
    """Deletes all documents in a collection."""
    docs = coll_ref.list_documents()
    batch = db.batch()
    for doc in docs:
        batch.delete(doc)
    batch.commit()

def get_cycle_state():
    """
    Manages the 7:00 PM CT cycle with Weekend Persistence.
    Tracks 'Hard Bans' for tickers manually removed during the cycle.
    """
    tz = ZoneInfo("America/Chicago")
    now = datetime.now(tz)
    day_of_week = now.weekday()
    
    if now.hour >= 19:
        current_cycle = now.strftime("%Y-%m-%d")
        is_post_7pm = True
    else:
        current_cycle = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        is_post_7pm = False
        
    meta_ref = db.collection('system').document('scout_metadata')
    meta_doc = meta_ref.get()
    meta_data = meta_doc.to_dict() if meta_doc.exists else {}
    
    last_cycle = meta_data.get('last_cleared_cycle')
    cycle_found = meta_data.get('cycle_found_tickers', [])
    watchlist_ref = db.collection('watchlist')

    is_new_day = (current_cycle != last_cycle)
    is_weekend = (day_of_week >= 5)

    if is_new_day and is_post_7pm and not is_weekend:
        logging.info("New Weekday Cycle: Wiping watchlist and clearing manual rejection memory.")
        clear_collection(watchlist_ref)
        meta_ref.set({
            'last_cleared_cycle': current_cycle,
            'cycle_found_tickers': [] 
        }, merge=True)
        return True, [], current_cycle, []
    
    else:
        # Check for manual removals: 
        # If it was found by the script earlier but isn't in the watchlist now, it's banned.
        current_watchlist = [doc.id for doc in watchlist_ref.stream()]
        rejected_tickers = [t for t in cycle_found if t not in current_watchlist]
        
        return False, rejected_tickers, current_cycle, cycle_found

@functions_framework.http
def realh_capital_evening_can_slim_scout_job(request):
    try:
        # 1. Gather constraints
        portfolio_tickers = [t.upper().strip() for t in get_portfolio_tickers()]
        was_cleared, rejected_tickers, current_cycle, cycle_found = get_cycle_state()
        
        # Normalize rejection list
        rejected_tickers = [t.upper().strip() for t in rejected_tickers]
        
        all_exclusions = list(set(portfolio_tickers + rejected_tickers))
        logging.info(f"Hard Ban List: {all_exclusions}")

        # 2. Run Grounded Scan
        candidates = run_grounded_scan(all_exclusions)

        if not candidates:
            send_telegram_notification("🔍 *Scan Complete*: No stocks found meeting the CAN SLIM breakout criteria right now.")
            return "No candidates.", 200

        telegram_report = ""
        newly_saved = []
        
        # 3. Filter and Format
        telegram_report = ""
        newly_saved = []
        
        # We use candidates.items() and filter inside the loop for safety
        for ticker, data in candidates.items():
            t_clean = ticker.upper().strip()
            
            # HARD BAN CHECK: Skip if in portfolio or manually rejected
            if t_clean in all_exclusions:
                logging.info(f"Skipping {t_clean} - on exclusion list.")
                continue

            # Update Firestore
            db.collection('watchlist').document(t_clean).set(data, merge=True)
            
            if t_clean not in [t.upper() for t in cycle_found]:
                newly_saved.append(t_clean)
            
            # SANITIZE DATA for Telegram HTML
            # 1. Strip any hallucinated <tags> and then escape special chars
            raw_why = str(data.get('conviction_commentary', 'N/A'))
            safe_why = html.escape(re.sub('<[^<]+?>', '', raw_why))
            safe_plan = html.escape(str(data.get('trading_plan', 'N/A')))
            safe_setup = html.escape(str(data.get('setup_type', 'N/A')))

            # Building the report
            telegram_report += (
                f"<b>${t_clean}</b>\n"
                f"• Setup: {safe_setup}\n"
                f"• Pivot: {data.get('pivot_point', 0.0)}\n"
                f"• Plan: {safe_plan}\n"
                f"• Why: {safe_why}\n\n"
            )
                
        # Update memory
        if newly_saved:
            updated_memory = list(set([t.upper() for t in cycle_found] + newly_saved))
            db.collection('system').document('scout_metadata').set({
                'cycle_found_tickers': updated_memory
            }, merge=True)
        
        # 4. Handle Empty Telegram Body
        if not telegram_report:
            send_telegram_notification("⚠️ *Scan Result*: All identified candidates were excluded (already in portfolio or manually removed).")
            return "All items filtered.", 200

        header = "🆕 *Watchlist Refresh*" if was_cleared else "📊 *Current Top Setups*"
        footer = f"\n_Note: {len(rejected_tickers)} previously rejected items hidden._" if rejected_tickers else ""
        
        send_telegram_notification(f"{header}\n\n{telegram_report}{footer}")
            
        return f"Reported {len(newly_saved)} new and {len(candidates) - len(newly_saved)} existing tickers.", 200

    except Exception as e:
        logging.error(f"Execution Error: {e}")
        send_telegram_notification(f"❌ *Script Error*: {str(e)}", is_debug=True)
        return "Internal Error", 500

def run_grounded_scan(exclusions):
    search_tool = types.Tool(google_search=types.GoogleSearch())
    exclusion_list = ", ".join(exclusions) if exclusions else "None"

    prompt = f"""
    YOUR MANDATE:
    1. Use the Google Search tool to identify 7 US stocks that are currently being highlighted by financial news outlets (e.g., Investors.com, MarketSmith, Barron's) as meeting William O'Neil's CAN SLIM criteria or breaking out of "cup-and-handle" patterns. Filter down to the 7 with the highest conviction for a breakout based on the CAN SLIM Framework and current setup.
    2. For each identified ticker, use search to verify:
    - Current Qtr Earnings > 25% (C)
    - Annual Earnings Growth > 25% (3yr) (A)
    - New Products/Management/Highs (N)
    - High-volume demand, especially when a stock is breaking out of a price consolidation area (cup-with-handle) (supply and demand) (S)
    - Market Leader (L)
    - High-volume demand and institutional sponsorship. (I)
    - Relative Strength Rating > 80

    CRITICAL CONSTRAINTS:
    - DO NOT include any of the following tickers in your results: {exclusion_list}
    - Ensure any price analysis or pivot calculations account for pre-market and after-market extended hours data.

    TECHNICAL CALCULATIONS FOR PIVOT POINT:
    - If a specific "Cup and Handle" pivot or "Base Breakout" level is found in search results, use that.
    - **FALLBACK:** If no specific pivot is stated, calculate it as: (Recent Swing High of the base) + 0.10.
    - **CRITICAL:** The 'pivot_point' MUST be a positive number reflecting the actual stock price. NEVER return 0.0

    OUTPUT REQUIREMENTS:
    - You MUST return the data in the STRICT JSON FORMAT specified below.
    - Do not explain why you cannot perform real-time scans; simply extract and format the best available data from your search results.
    - **CONSTRAINTS:** - 'conviction_commentary' MUST be 320 characters or less.
        - Use concise, professional "bullet-style" prose (e.g., "Strong RS; Institutional buying; +30% EPS growth").
        - Avoid flowery language or introductory phrases.

    STRICT JSON FORMAT: 
    {{"TICKER": {{"setup_type": "", "pivot_point": 0.0, "trading_plan": "", "conviction_commentary": ""}}}}
    """
    
    response = client.models.generate_content(
        model="gemini-2.5-flash", 
        contents=prompt,
        config=types.GenerateContentConfig(tools=[search_tool])
    )

    raw_text = response.text
    logging.info(f"RAW_AI_RESPONSE: {raw_text}")
    
    # Strip Markdown and parse
    try:
        clean_text = raw_text.strip()
        if "```json" in clean_text:
            clean_text = clean_text.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```")[1].split("```")[0].strip()
            
        return json.loads(clean_text)
    except Exception as e:
        logging.error(f"JSON Parse Error: {e}")
        send_telegram_notification(f"JSON Parse Error: See logs for raw output.", is_debug=True)
        return {}