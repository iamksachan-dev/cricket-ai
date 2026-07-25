# ============================================================
# 🏏 ULTIMATE CRICKET AI – Railway Deployment
#        Developed by Kartikey Sachan
# ============================================================

import os
import warnings
warnings.filterwarnings("ignore")

import gdown
import duckdb
import gradio as gr
import re
import requests
from datetime import datetime

from groq import Groq
from google import genai
from google.genai import types
from openai import OpenAI
from duckduckgo_search import DDGS

# ============================================================
# 🔑 API KEYS (Hardcoded for this deployment)
# ============================================================
GROQ_API_KEY = "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"
GEMINI_API_KEY = "AQ.Ab8RN6LpSnSVn5MlD1qV3QwuZIsKD8XuNCNZ6pInk0wTdXWl5g"
MISTRAL_API_KEY = "eB6PwGvxzWnHkqob6zEKJmBvVOPviAD5"
CRICAPI_KEY = "a6ff2bd0-19c9-4bf8-9b6e-5c5cf23bccad"
RAPIDAPI_KEY = "e3d47d7ee3msh15e18bc016c3bb2p16c3d4jsn2762c63da0ff"

# ============================================================
# 📂 DATA – Download once, query directly (memory‑efficient)
# ============================================================
FILE_ID = "1rnUshf-no-AVNUvZjOvh86vPuKFRXZ2h"
DATA_PATH = "master_cricket_stats.parquet"

if not os.path.exists(DATA_PATH):
    print("📥 Downloading 400 MB data from Google Drive...")
    gdown.download(f"https://drive.google.com/uc?id={FILE_ID}", DATA_PATH, quiet=False)
    print("✅ Download complete!")

db = duckdb.connect(':memory:')
try:
    count = db.execute(f"SELECT COUNT(*) FROM read_parquet('{DATA_PATH}')").fetchone()[0]
    print(f"✅ Data ready: {count:,} deliveries (queried on‑demand).")
except Exception as e:
    print(f"⚠️ Data error: {e}")

# ============================================================
# 🤖 AI CLIENTS
# ============================================================
groq_client = Groq(api_key=GROQ_API_KEY)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
mistral_client = OpenAI(api_key=MISTRAL_API_KEY, base_url="https://api.mistral.ai/v1")

# ============================================================
# 🌐 HELPER FUNCTIONS (Direct Parquet queries – Memory Safe)
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
    if not player_name: return None
    try:
        query = f"""
        SELECT 
            SUM(runs) AS total_runs,
            COUNT(DISTINCT match_file) AS matches_played,
            AVG(runs) AS avg_runs_per_delivery
        FROM read_parquet('{DATA_PATH}')
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
    if not player or not bowler: return None
    try:
        query = f"""
        SELECT 
            SUM(runs) AS total_runs,
            COUNT(*) AS balls_faced
        FROM read_parquet('{DATA_PATH}')
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
    You are a World-Class Cricket Analyst. Use all the provided data and your cricket knowledge to give a comprehensive, tactical answer.

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
# 💬 CHAT FUNCTION
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
# 🖥️ GRADIO INTERFACE
# ============================================================
chatbot = gr.Chatbot(
    value=[{"role": "assistant", "content": "I am your cricket AI developed by Kartikey Sachan. How may I help you?"}],
    height=500
)

iface = gr.ChatInterface(
    fn=chat_function,
    title="🏏 Ultimate Cricket AI – Developed by Kartikey Sachan",
    chatbot=chatbot
)

# ✅ Railway‑compatible launch: bind to 0.0.0.0 and use $PORT
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    iface.launch(server_name="0.0.0.0", server_port=port)
