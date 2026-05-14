from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import json
import base64
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = "fofankochevnik/fofankochevnik.github.io"
GITHUB_BRANCH = "main"

SUBJECTS = [
    {"id": "math",  "keywords": ["математик"]},
    {"id": "rus",   "keywords": ["русский", "русск", "русяз"]},
    {"id": "lit",   "keywords": ["литератур", "лит чтен"]},
    {"id": "eng",   "keywords": ["английск", "англ"]},
    {"id": "okr",   "keywords": ["окружающ", "окр мир"]},
]

def fix_transcript(raw_text):
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "inclusion/ring-2.6-1t:free",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ты помощник, который исправляет транскрипт OCR русского текста. "
                        "Тебе дают текст из расписания школьного дневника, где русские слова "
                        "написаны латиницей (транслитерация) или с ошибками OCR. "
                        "Верни ТОЛЬКО исправленный русский текст в том же формате, без пояснений. "
                        "Сохраняй эмодзи 📅 🏠 ⇨ и структуру строк."
                    )
                },
                {"role": "user", "content": raw_text}
            ],
            "max_tokens": 1500,
        },
        timeout=30
    )
    data = resp.json()
    return data["choices"][0]["message"]["content"]

def parse_schedule(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    result = {}
    current_subject = None

    for i, line in enumerate(lines):
        import re
        lesson_match = re.match(r"^\d+:\s*(.+?),?\s*\d{1,2}:\d{2}", line)
        if lesson_match:
            subject_raw = lesson_match.group(1).lower()
            current_subject = None
            for s in SUBJECTS:
                if any(k in subject_raw for k in s["keywords"]):
                    current_subject = s["id"]
                    break
            continue

        if line.startswith("🏠") and current_subject:
            hw = line.replace("🏠", "").strip()
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                if re.match(r"^\d+:", next_line) or next_line.startswith("🏠") or next_line.startswith("⇨"):
                    break
                hw += " " + next_line
                j += 1
            result[current_subject] = hw.strip()

    return result

def save_to_github(hw_data, date_str):
    content = json.dumps({
        "date": date_str,
        "subjects": [{"id": k, "hw": v} for k, v in hw_data.items()]
    }, ensure_ascii=False, indent=2)

    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }

    # Получаем sha
    sha = ""
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/homework.json",
        headers=headers
    )
    if r.ok:
        sha = r.json().get("sha", "")

    body = {
        "message": f"update homework {date_str}",
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/homework.json",
        headers=headers,
        json=body,
        timeout=15
    )
    return resp.ok

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "msg": "homework backend running"})

@app.route("/update", methods=["POST"])
def update():
    data = request.get_json(silent=True) or {}
    raw_text = data.get("raw_text", "").strip()

    if not raw_text:
        return jsonify({"error": "raw_text is empty"}), 400

    try:
        fixed = fix_transcript(raw_text)
    except Exception as e:
        return jsonify({"error": f"OpenRouter error: {e}"}), 500

    hw_data = parse_schedule(fixed)

    if not hw_data:
        return jsonify({"error": "nothing parsed", "fixed_text": fixed}), 422

    date_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    ok = save_to_github(hw_data, date_str)

    if not ok:
        return jsonify({"error": "github save failed"}), 500

    return jsonify({"ok": True, "date": date_str, "subjects": hw_data})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
