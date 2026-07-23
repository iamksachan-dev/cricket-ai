# ============================================================
# 🏏 ULTIMATE CRICKET AI – Developed by Kartikey Sachan
#        Deployable Version (Reads Keys from .env / Secrets)
# ============================================================

import os
import warnings
warnings.filterwarnings("ignore")

import gdown
import duckdb
import pandas as pd
import gradio as gr
import re
import requests
from datetime import datetime

# --- AI Libraries ---
from groq import Groq
from google import genai
from google.genai import types
from openai import OpenAI

# --- Web Search ---
from duckduckgo_search import DDGS

# ============================================================
# 🔑 1. READ API KEYS FROM ENVIRONMENT VARIABLES (SECURE)
# ============================================================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
CRICAPI_KEY = os.environ.get("CRICAPI_KEY")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")

# Check if keys are loaded (optional warning)
if not all([GROQ_API_KEY, GEMINI_API_KEY, MISTRAL_API_KEY]):
    print("⚠️ WARNING: Some AI API keys are missing. Please set them in environment variables.")

# ============================================================
# 📂 2. LOAD / DOWNLOAD DATA (From Google Drive)
# ============================================================
# Folder where Hugging Face / Streamlit expect persistent data
DATA_DIR = "/data" if os.path.exists("/data") else os.getcwd()
PARQUET_PATH = os.path.join(DATA_DIR, "master_cricket_stats.parquet")
FILE_ID = "1rnUshf-no-AVNUvZjOvh86vPuKFRXZ2h"  # Your Google Drive File ID

def load_data():
    if os.path.exists(PARQUET_PATH):
        print(f"✅ Data found locally: {PARQUET_PATH}")
        return duckdb.connect(':memory:'), PARQUET_PATH
    
    print("📥 Data not found locally. Downloading 400MB from Google Drive (First time only)...")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        url = f"https://drive.google.com/uc?id={FILE_ID}"
        gdown.download(url, PARQUET_PATH, quiet=False)
        print("✅ Download complete!")
        return duckdb.connect(':memory:'), PARQUET_PATH
    except Exception as e:
        print(f"❌ Download failed: {e}")
        # Fallback to empty database so the app doesn't crash
        db = duckdb.connect(':memory:')
        db.execute("CREATE TABLE matches AS SELECT 'No data' as venue, 'Unknown' as match_type, 'Unknown' as season, 'Unknown' as batting_team, 'Unknown' as bowling_team, 'Unknown' as batsman, 'Unknown' as bowler, 0 as runs WHERE 1=0")
        return db, None

# Initialize DB
db, data_path = load_data()
if data_path:
    db.execute(f"CREATE OR REPLACE TABLE matches AS SELECT * FROM read_parquet('{data_path}')")
    count = db.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    print(f"✅ Loaded {count:,} deliveries successfully!")
else:
    count = 0

# ============================================================
# 🌐 3. INITIALIZE AI CLIENTS
# ============================================================
groq_client = Groq(api_key=GROQ_API_KEY)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
mistral_client = OpenAI(api_key=MISTRAL_API_KEY, base_url="https://api.mistral.ai/v1")

# ============================================================
# 🛠️ 4. HELPER FUNCTIONS (Search, Weather, Live Scores, Stats)
# ============================================================

def search_web(query, max_results=5):
    try:
        with DDGS() as ddgs:
            results = []
            for r in ddgs.text(query, max_results=max_results):
                results.append({"title": r.get("title", ""), "body": r.get("body", ""), "link": r.get("href", "")})
            return results
    except:
        return []

STADIUM_MAP = {"wankhede": "Mumbai", "eden gardens": "Kolkata", "chinnaswamy": "Bengaluru",
               "narendra modi": "Ahmedabad", "lords": "London", "mcg": "Melbourne"}

def get_weather_via_search(city_name):
    city_clean = city_name.strip()
    for stadium, city in STADIUM_MAP.items():
        if stadium in city_clean.lower():
            city_clean = city
            break
    results = search_web(f"current weather in {city_clean}", max_results=2)
    if not results: return "⚠️ No weather data."
    weather_text = f"📍 Location: {city_clean}\n"
    for r in results: weather_text += f"📌 {r['body'][:300]}...\n"
    return weather_text

def fetch_rapidapi_live():
    try:
        url = "https://cricket-api17.p.rapidapi.com/api/v2/getHome"
        headers = {"Content-Type": "application/json",
                   "x-rapidapi-host": "cricket-api17.p.rapidapi.com",
                   "x-rapidapi-key": RAPIDAPI_KEY}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                for key in ['data', 'matches', 'liveMatches', 'items']:
                    if key in data and isinstance(data[key], list): return data[key]
                return data
            elif isinstance(data, list): return data
        return []
    except: return []

def fetch_cricapi_live():
    try:
        url = f"https://api.cricapi.com/v1/currentMatches?apikey={CRICAPI_KEY}&offset=0"
        r = requests.get(url, timeout=10)
        if r.status_code == 200 and r.json().get("status") == "success":
            return r.json().get("data", [])
        return []
    except: return []

def fetch_live_matches():
    m = fetch_rapidapi_live()
    return m if m else fetch_cricapi_live()

def format_live_matches(matches):
    if not matches: return "No live matches."
    output = "🏏 **Live Matches**\n"
    if isinstance(matches, dict): matches = [matches]
    for m in matches[:10]:
        name = m.get('name') or m.get('title') or 'Match'
        status = m.get('status') or 'Live'
        t1 = m.get('team1') or m.get('teamA') or 'Team A'
        t2 = m.get('team2') or m.get('teamB') or 'Team B'
        s1 = m.get('score1') or m.get('teamAScore') or ''
        s2 = m.get('score2') or m.get('teamBScore') or ''
        output += f"• **{name}**\n  {status}\n  {t1}: {s1} | {t2}: {s2}\n\n"
    return output

def get_player_stats(player_name):
    if not player_name or count == 0: return None
    try:
        query = f"""
        SELECT 
            SUM(runs) AS total_runs,
            COUNT(DISTINCT match_file) AS matches_played,
            AVG(runs) AS avg_runs_per_delivery
        FROM matches
        WHERE batsman = '{player_name}'
        GROUP BY batsman
        """
        result = db.execute(query).fetchdf()
        if len(result) == 0: return None
        row = result.iloc[0]
        return {
            "batsman": player_name,
            "total_runs": int(row['total_runs']),
            "matches": int(row['matches_played']),
            "avg_per_delivery": float(row['avg_runs_per_delivery']),
            "strike_rate": float(row['avg_runs_per_delivery']) * 100
        }
    except: return None

def get_head_to_head(player, bowler):
    if not player or not bowler or count == 0: return None
    try:
        query = f"""
        SELECT 
            SUM(runs) AS total_runs,
            COUNT(*) AS balls_faced
        FROM matches
        WHERE batsman = '{player}' AND bowler = '{bowler}'
        GROUP BY batsman, bowler
        """
        result = db.execute(query).fetchdf()
        if len(result) == 0: return None
        row = result.iloc[0]
        return {
            "runs": int(row['total_runs']),
            "balls": int(row['balls_faced']),
            "avg_per_100": round(float(row['total_runs']) / float(row['balls_faced']) * 100, 2)
        }
    except: return None

# ============================================================
# 🤖 5. AI CORE FUNCTIONS (Extract, Research, Generate)
# ============================================================
def extract_player_names(question):
    prompt = f"Extract the cricketer name(s) from this question: '{question}'. Return only the names, comma-separated. If no player, return 'None'."
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0, max_tokens=50, timeout=5
        )
        text = response.choices[0].message.content
        if "None" in text: return []
        return [n.strip() for n in text.split(',') if n.strip()]
    except: return []

def gemini_grounded_research(question):
    try:
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.1, max_output_tokens=500
        )
        response = gemini_client.models.generate_content(
            model='gemini-2.0-flash-exp',
            contents=f"Provide up‑to‑date verified cricket facts for: {question}",
            config=config
        )
        return response.text
    except Exception as e:
        return f"[Gemini Research Error: {e}]"

def call_mistral(prompt, timeout=20):
    try:
        response = mistral_client.chat.completions.create(
            model="mistral-large-latest",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=800, timeout=timeout
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"[Mistral Error: {str(e)[:100]}]"

def generate_answer(question, player_stats, h2h_stats, weather="", live="", web_research=""):
    prompt = f"""
    You are a World-Class Cricket Analyst. Use all the provided data and your cricket knowledge.

    USER QUESTION: {question}
    """
    if player_stats:
        prompt += f"""
    **PLAYER STATS:**
    - Total Runs: {player_stats['total_runs']}
    - Matches: {player_stats['matches']}
    - Avg per delivery: {player_stats['avg_per_delivery']:.2f}
    - Strike Rate: {player_stats['strike_rate']:.2f}
    """
    if h2h_stats:
        prompt += f"""
    **HEAD-TO-HEAD:**
    - Runs: {h2h_stats['runs']} | Balls: {h2h_stats['balls']}
    - Avg per 100 balls: {h2h_stats['avg_per_100']}
    """
    if weather: prompt += f"\n**WEATHER:** {weather}\n"
    if live: prompt += f"\n**LIVE SCORES:** {live}\n"
    if web_research: prompt += f"\n**WEB RESEARCH:**\n{web_research}\n"

    prompt += """
    OUTPUT FORMAT:
    📊 **Data Insight:** [Key numbers]
    📈 **Analysis:** [Meaning]
    🎯 **Plan-A:** [Action]
    🔄 **Plan-B:** [Alternative]
    ⚠️ **Risk Warning:** [Risks]
    """
    return call_mistral(prompt)

# ============================================================
# 💬 6. MAIN CHAT FUNCTION
# ============================================================
def chat_function(message, history):
    print(f"\n🧠 User: {message}")

    weather_text = ""
    live_text = ""
    web_research = ""

    if "weather" in message.lower():
        city = re.search(r'in\s+([A-Za-z\s]+)', message, re.I)
        weather_text = get_weather_via_search(city.group(1).strip() if city else "London")

    if any(k in message.lower() for k in ["live", "score", "today"]):
        live_data = fetch_live_matches()
        if live_data: live_text = format_live_matches(live_data)

    player_names = extract_player_names(message)
    bowler = None
    if "against" in message.lower() or "vs" in message.lower():
        parts = re.split(r'\b(?:against|vs)\b', message, flags=re.I)
        if len(parts) > 1:
            potential = parts[1].strip().split()[0]
            if potential and potential[0].isupper():
                bowler = potential

    player_stats = None
    h2h_stats = None
    if player_names:
        player_stats = get_player_stats(player_names[0])
        if bowler:
            h2h_stats = get_head_to_head(player_names[0], bowler)

    gemini_research = gemini_grounded_research(message)
    if "[Gemini Research Error" not in gemini_research:
        web_research = gemini_research
    else:
        ddg_results = search_web(message + " cricket", max_results=4)
        if ddg_results:
            web_research = "\n".join([f"• {r['title']}: {r['body'][:200]}..." for r in ddg_results])

    answer = generate_answer(message, player_stats, h2h_stats, weather_text, live_text, web_research)
    return answer

# ============================================================
# 🖥️ 7. LAUNCH GRADIO INTERFACE
# ============================================================

# Create Chatbot with greeting
chatbot = gr.Chatbot(
    value=[{"role": "assistant", "content": "I am your cricket AI developed by Kartikey Sachan. How may I help you?"}],
    height=500
)

iface = gr.ChatInterface(
    fn=chat_function,
    title="🏏 Ultimate Cricket AI – Developed by Kartikey Sachan",
    chatbot=chatbot
)

# For Streamlit Cloud / Hugging Face, we just use launch()
iface.launch()
