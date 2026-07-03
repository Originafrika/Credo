from flask import Flask, render_template, request, jsonify, session
import sqlite3
import os
import uuid
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'credo-dev-2026')

DB_PATH = os.environ.get('CREDO_DB_PATH', '/tmp/credo.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id TEXT, phone TEXT, name TEXT, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS evaluations
                 (id TEXT, user_id TEXT, status TEXT, score INTEGER,
                  max_amount INTEGER, partner TEXT, paid INTEGER,
                  created_at TEXT)''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/pay', methods=['POST'])
def pay():
    data = request.json
    phone = data.get('phone')
    amount = data.get('amount', 2500)
    eval_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO evaluations (id, user_id, status, paid, created_at) VALUES (?, ?, ?, ?, ?)",
              (eval_id, phone, 'pending', 1, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'eval_id': eval_id, 'redirect': f'/chat/{eval_id}'})

@app.route('/chat/new')
def chat_new():
    return render_template('chat_new.html')

@app.route('/chat/<eval_id>')
def chat(eval_id):
    return render_template('chat.html', eval_id=eval_id)

@app.route('/api/analyze', methods=['POST'])
def analyze():
    data = request.json
    answers = data.get('answers', [])
    score = min(100, max(0, 35 + len(answers) * 5))
    partners = [
        {'name': 'FUCEC-Togo', 'amount': 500000, 'rate': '12%'},
        {'name': 'UBT', 'amount': 300000, 'rate': '15%'},
        {'name': 'WAGES', 'amount': 200000, 'rate': '10%'}
    ]
    return jsonify({
        'score': score,
        'risk': 'Faible' if score > 65 else 'Moyen' if score > 40 else 'Élevé',
        'max_amount': max(p['amount'] for p in partners),
        'partners': partners,
        'advice': 'Augmente ton apport personnel pour atteindre 1M FCFA.'
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
