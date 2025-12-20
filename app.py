import streamlit as st
import os
import sqlite3
import hashlib
import json
import time
import re
import pandas as pd
import base64
from collections import Counter
from datetime import datetime
from pypdf import PdfReader
from streamlit_pdf_viewer import pdf_viewer
import google.generativeai as genai

# --- 1. SETUP & CONFIGURATION ---
st.set_page_config(page_title="IITConnect", page_icon="🎓", layout="wide")

# PASTE YOUR API KEY HERE
GOOGLE_API_KEY = "AIzaSyB5QPNOt0s_9iKnawAIa8zzSb4yNr6KQ8k"

if GOOGLE_API_KEY != "PASTE_YOUR_API_KEY_HERE":
    genai.configure(api_key=GOOGLE_API_KEY)

# CONSTANTS
DB_NAME = "iitconnect_v30.db"
UPLOAD_FOLDER = "uploaded_notes"
if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)

# --- 2. MODERN CSS STYLING ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* 1. GENERAL BUTTON STYLING */
    div.stButton > button {
        width: 100%; border-radius: 12px; height: 3.2em;
        background-color: #2b2d42; color: white; border: 1px solid #3d405b;
        font-weight: 500; transition: all 0.3s ease;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }
    div.stButton > button:hover {
        border-color: #ff5722; background-color: #3d405b;
        transform: translateY(-2px); box-shadow: 0 4px 8px rgba(0,0,0,0.2);
    }

    /* 2. SIDEBAR STYLING */
    section[data-testid="stSidebar"] { background-color: #1a1a1a; }
    section[data-testid="stSidebar"] div.stButton > button {
        text-align: left; padding-left: 20px; border: none; background-color: transparent;
    }
    section[data-testid="stSidebar"] div.stButton > button:hover {
        background-color: #333; color: #ff5722;
    }

    /* 3. GOOGLE-STYLE PROFILE BUTTON */
    div[data-testid="stSidebar"] div[data-testid="element-container"]:nth-child(1) button {
        border-radius: 50% !important; height: 80px !important; width: 80px !important;
        margin: 0 auto !important; display: block !important;
        background: linear-gradient(135deg, #ff5722, #ff8a65) !important;
        color: white !important; font-size: 32px !important; font-weight: 800 !important;
        border: 3px solid #1a1a1a !important;
        box-shadow: 0 4px 15px rgba(255, 87, 34, 0.4) !important;
        padding: 0 !important; overflow: hidden !important;
    }

    /* 4. FEED & GENERAL */
    div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlock"] { gap: 1rem; }
    thead tr th { background-color: #1e1e1e !important; color: #ff5722 !important; font-size: 16px !important; border-bottom: 2px solid #333 !important; }
    h1, h2, h3 { color: #f0f0f0; font-weight: 700; letter-spacing: -0.5px; }
</style>
""", unsafe_allow_html=True)

# --- 3. DATABASE MANAGEMENT ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON;")
    c.execute('''CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, uploader TEXT, subject TEXT, title TEXT, filename TEXT, upvotes INTEGER, is_verified INTEGER, tags TEXT, timestamp DATETIME, content TEXT, post_type TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY, target_id INTEGER, target_type TEXT, parent_id INTEGER, user TEXT, comment TEXT, timestamp DATETIME)''')
    c.execute('''CREATE TABLE IF NOT EXISTS answers (id INTEGER PRIMARY KEY, doubt_id INTEGER, responder TEXT, answer_text TEXT, upvotes INTEGER, timestamp DATETIME)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, posts_count INTEGER DEFAULT 0, answers_count INTEGER DEFAULT 0, upvotes_received INTEGER DEFAULT 0, reputation INTEGER DEFAULT 0, full_name TEXT, college TEXT, year TEXT, branch TEXT, age TEXT, gender TEXT, bio TEXT, profile_pic TEXT, is_active INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS votes (user TEXT, item_id INTEGER, item_type TEXT, vote_type INTEGER, PRIMARY KEY (user, item_id, item_type))''')
    c.execute('''CREATE TABLE IF NOT EXISTS bookmarks (user TEXT, note_id INTEGER, timestamp DATETIME, PRIMARY KEY (user, note_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY, user TEXT, message TEXT, is_read INTEGER DEFAULT 0, timestamp DATETIME)''')
    c.execute('''CREATE TABLE IF NOT EXISTS course_requests (id INTEGER PRIMARY KEY, user TEXT, course_name TEXT, reason TEXT, timestamp DATETIME)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, reporter TEXT, post_id INTEGER, reason TEXT, details TEXT, status TEXT DEFAULT 'Pending', timestamp DATETIME)''')
    conn.commit(); conn.close()

# --- 4. AUTH & HELPERS ---
def make_hash(password): return hashlib.sha256(str.encode(password)).hexdigest()
def register_user(username, password, college):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    try: c.execute("INSERT INTO users (username, password, college, is_active) VALUES (?, ?, ?, 1)", (username, make_hash(password), college)); conn.commit(); return True
    except: return False
    finally: conn.close()
def login_user(username, password):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, make_hash(password)))
    data = c.fetchone()
    if data and data[14] == 0: c.execute("UPDATE users SET is_active = 1 WHERE username = ?", (username,)); conn.commit(); st.toast("Reactivated!")
    conn.close(); return data

# --- STATS, BADGES & PROFILE ---
def get_user_badge(reputation):
    if reputation > 500: return "🟣 Professor"
    elif reputation > 200: return "🟡 Scholar"
    elif reputation > 50: return "🔵 Contributor"
    return "⚪ Fresher"

def get_user_stats_detailed(username):
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (username,)); user_data = c.fetchone()
    if not user_data: return None, 0, 0
    c.execute("SELECT COUNT(*) FROM notes WHERE uploader = ? AND post_type = 'DOUBT'", (username,)); doubts = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM notes WHERE uploader = ? AND post_type = 'RESOURCE'", (username,)); notes = c.fetchone()[0]
    conn.close(); return user_data, doubts, notes

def update_reputation(username):
    if username == "Anonymous": return
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("SELECT posts_count, answers_count, upvotes_received FROM users WHERE username=?", (username,))
    res = c.fetchone()
    if res:
        new_rep = (res[2] * 2) + (res[0] * 5) + (res[1] * 3)
        c.execute("UPDATE users SET reputation = ? WHERE username = ?", (new_rep, username))
        conn.commit()
    conn.close()

def update_user_profile(username, full_name, year, branch, age, gender, bio, pic_data):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("UPDATE users SET full_name=?, year=?, branch=?, age=?, gender=?, bio=?, profile_pic=? WHERE username=?", 
              (full_name, year, branch, age, gender, bio, pic_data, username))
    conn.commit(); conn.close()

def change_username(old_user, new_user):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    try:
        c.execute("UPDATE users SET username = ? WHERE username = ?", (new_user, old_user))
        c.execute("UPDATE notes SET uploader = ? WHERE uploader = ?", (new_user, old_user))
        c.execute("UPDATE answers SET responder = ? WHERE responder = ?", (new_user, old_user))
        c.execute("UPDATE comments SET user = ? WHERE user = ?", (new_user, old_user))
        c.execute("UPDATE votes SET user = ? WHERE user = ?", (new_user, old_user))
        c.execute("UPDATE bookmarks SET user = ? WHERE user = ?", (new_user, old_user))
        c.execute("UPDATE notifications SET user = ? WHERE user = ?", (new_user, old_user))
        conn.commit(); return True
    except: return False
    finally: conn.close()

def delete_account(username):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("DELETE FROM users WHERE username = ?", (username,))
    c.execute("DELETE FROM notes WHERE uploader = ?", (username,))
    c.execute("DELETE FROM answers WHERE responder = ?", (username,))
    c.execute("DELETE FROM comments WHERE user = ?", (username,))
    c.execute("DELETE FROM votes WHERE user = ?", (username,))
    conn.commit(); conn.close()

def deactivate_account(username):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("UPDATE users SET is_active = 0 WHERE username = ?", (username,)); conn.commit(); conn.close()

# --- NOTIFICATIONS, BOOKMARKS & REPORTS ---
def add_notification(target_user, message):
    if target_user == st.session_state.user or target_user == "Anonymous": return
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("INSERT INTO notifications (user, message, timestamp) VALUES (?, ?, ?)", (target_user, message, datetime.now()))
    conn.commit(); conn.close()

def get_unread_notifications(user):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM notifications WHERE user=? AND is_read=0", (user,))
    count = c.fetchone()[0]
    c.execute("SELECT * FROM notifications WHERE user=? ORDER BY timestamp DESC LIMIT 10", (user,))
    notes = c.fetchall(); conn.close(); return count, notes

def mark_notifications_read(user):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("UPDATE notifications SET is_read=1 WHERE user=?", (user,)); conn.commit(); conn.close()

def toggle_bookmark(note_id):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("SELECT * FROM bookmarks WHERE user=? AND note_id=?", (st.session_state.user, note_id))
    if c.fetchone():
        c.execute("DELETE FROM bookmarks WHERE user=? AND note_id=?", (st.session_state.user, note_id))
        msg = "Removed"
    else:
        c.execute("INSERT INTO bookmarks VALUES (?, ?, ?)", (st.session_state.user, note_id, datetime.now()))
        msg = "Saved"
    conn.commit(); conn.close(); st.toast(f"Bookmark {msg}"); st.rerun()

def submit_course_request(user, course_name, reason):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("INSERT INTO course_requests (user, course_name, reason, timestamp) VALUES (?, ?, ?, ?)", (user, course_name, reason, datetime.now()))
    conn.commit(); conn.close()

def submit_report(post_id, reporter, reason, details):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("INSERT INTO reports (reporter, post_id, reason, details, timestamp) VALUES (?, ?, ?, ?, ?)", (reporter, post_id, reason, details, datetime.now()))
    conn.commit(); conn.close()

# --- 5. CRUD ---
def delete_item(table, item_id):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    if table == "notes":
        c.execute("SELECT uploader FROM notes WHERE id=?", (item_id,)); user = c.fetchone()[0]
        c.execute("DELETE FROM notes WHERE id=?", (item_id,)); 
        if user != "Anonymous": c.execute("UPDATE users SET posts_count = posts_count - 1 WHERE username=?", (user,))
    elif table == "answers":
        c.execute("SELECT responder FROM answers WHERE id=?", (item_id,)); user = c.fetchone()[0]
        c.execute("DELETE FROM answers WHERE id=?", (item_id,)); 
        if user != "Anonymous": c.execute("UPDATE users SET answers_count = answers_count - 1 WHERE username=?", (user,))
    else: c.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
    conn.commit(); conn.close(); 
    if user != "Anonymous": update_reputation(user if table in ['notes', 'answers'] else st.session_state.user)
    st.toast(f"{table[:-1].title()} Deleted"); st.rerun()

def edit_item(table, item_id, new_text, column="content"):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (new_text, item_id)); conn.commit(); conn.close(); st.toast("Updated"); st.rerun()

def update_post(note_id, new_title, new_content):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("UPDATE notes SET title=?, content=? WHERE id=?", (new_title, new_content, note_id)); conn.commit(); conn.close(); st.toast("Updated"); st.rerun()

def handle_vote(item_id, item_type, voter, direction):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    table = "notes" if item_type == "NOTE" else "answers"
    c.execute(f"SELECT {'uploader' if item_type=='NOTE' else 'responder'} FROM {table} WHERE id = ?", (item_id,)); res = c.fetchone()
    if not res: return
    author = res[0]
    c.execute("SELECT vote_type FROM votes WHERE user=? AND item_id=? AND item_type=?", (voter, item_id, item_type))
    existing = c.fetchone(); change = 0
    if not existing:
        c.execute("INSERT INTO votes VALUES (?, ?, ?, ?)", (voter, item_id, item_type, direction))
        c.execute(f"UPDATE {table} SET upvotes = upvotes + ? WHERE id = ?", (direction, item_id)); change = direction
    elif existing[0] == direction:
        c.execute("DELETE FROM votes WHERE user=? AND item_id=? AND item_type=?", (voter, item_id, item_type))
        c.execute(f"UPDATE {table} SET upvotes = upvotes - ? WHERE id = ?", (direction, item_id)); change = -direction
    else:
        c.execute("UPDATE votes SET vote_type=? WHERE user=? AND item_id=? AND item_type=?", (direction, voter, item_id, item_type))
        c.execute(f"UPDATE {table} SET upvotes = upvotes + ? WHERE id = ?", (2*direction, item_id)); change = 2*direction
    if author != "Anonymous": c.execute("UPDATE users SET upvotes_received = upvotes_received + ? WHERE username = ?", (change, author))
    conn.commit(); conn.close(); 
    if author != "Anonymous": update_reputation(author)

def add_note(uploader, subject, title, filename, tags, verified, content="", post_type="RESOURCE"):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("INSERT INTO notes VALUES (NULL, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)", (uploader, subject, title, filename, 1 if verified else 0, tags, datetime.now(), content, post_type))
    if uploader != "Anonymous": c.execute("UPDATE users SET posts_count = posts_count + 1 WHERE username = ?", (uploader,))
    conn.commit(); conn.close(); 
    if uploader != "Anonymous": update_reputation(uploader)

def add_answer(doubt_id, user, text, original_uploader):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("INSERT INTO answers VALUES (NULL, ?, ?, ?, 0, ?)", (doubt_id, user, text, datetime.now()))
    if user != "Anonymous": c.execute("UPDATE users SET answers_count = answers_count + 1 WHERE username = ?", (user,))
    conn.commit(); conn.close(); 
    if user != "Anonymous": update_reputation(user)
    add_notification(original_uploader, f"{user} answered your doubt!")

def add_comment(target_id, target_type, user, text, parent_id=None, item_owner=None):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("INSERT INTO comments VALUES (NULL, ?, ?, ?, ?, ?, ?)", (target_id, target_type, parent_id, user, text, datetime.now())); conn.commit(); conn.close()
    if item_owner: add_notification(item_owner, f"{user} commented on your {target_type.lower()}.")

def get_data(query, params=()):
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute(query, params); return c.fetchall()

def search_notes(search_term, subject_filter=None, type_filter=None):
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    base = "SELECT * FROM notes WHERE (title LIKE ? OR tags LIKE ?)"
    params = [f"%{search_term}%", f"%{search_term}%"]
    if subject_filter: base += " AND subject = ?"; params.append(subject_filter)
    if type_filter: base += " AND post_type = ?"; params.append(type_filter)
    base += " ORDER BY timestamp DESC"
    c.execute(base, params); return c.fetchall()

def get_pdf_text(pdf_path):
    text = ""; 
    try: 
        reader = PdfReader(pdf_path); 
        for page in reader.pages: text += page.extract_text() or ""
    except: pass
    return text

# --- 6. AI LOGIC ---
def get_ai_model(): return genai.GenerativeModel("gemini-2.5-flash")

def clean_json_response(text):
    try: match = re.search(r'\[.*\]', text, re.DOTALL); return json.loads(match.group()) if match else json.loads(text)
    except: return None

def generate_ai_content(file_path, task_type, force_vision=False):
    if GOOGLE_API_KEY == "PASTE_YOUR_API_KEY_HERE": return None
    model = get_ai_model(); text = get_pdf_text(file_path)
    use_vision = force_vision or (len(text.strip()) < 100)
    
    prompts = {
        'mcq': 'Create 5 MCQs. JSON: [{"question":"...","options":["A","B","C","D"],"answer":"Exact Text","hint":"..."}]',
        'subjective': 'Create 5 short Qs. JSON: [{"question":"...","model_answer":"...","hint":"..."}]',
        'flashcard': 'Create 8 flashcards. JSON: [{"term":"...","definition":"..."}]',
        'summary': "Summarize in bullets. Return text."
    }
    for _ in range(2):
        try:
            if not use_vision: response = model.generate_content(f"{prompts[task_type]}\n\nText:\n{text[:8000]}")
            else:
                up = genai.upload_file(file_path, mime_type='application/pdf')
                while up.state.name == "PROCESSING": time.sleep(1); up = genai.get_file(up.name)
                response = model.generate_content([up, prompts[task_type]])
            if task_type == 'summary': return response.text
            data = clean_json_response(response.text)
            if data: return data
        except: time.sleep(1)
    return None

def verify_content_with_ai(text, subject):
    if GOOGLE_API_KEY == "PASTE_YOUR_API_KEY_HERE": return True, "Skipped"
    if not text or len(text.strip()) < 50: return True, "Scanned"
    try: r = get_ai_model().generate_content(f"Is SPAM? Sub: {subject}. Text: {text[:500]}. Output: VERDICT: [ACCEPT/REJECT]").text; return ("VERDICT: ACCEPT" in r), r 
    except: return True, "Error"

# --- 7. UI RENDERERS ---
def render_comments(target_id, target_type, parent_id=None, level=0):
    query = f"SELECT * FROM comments WHERE target_id=? AND target_type=? AND parent_id {'IS NULL' if parent_id is None else '=?'} ORDER BY timestamp ASC"
    params = (target_id, target_type) if parent_id is None else (target_id, target_type, parent_id)
    comments = get_data(query, params)
    for com in comments:
        with st.container():
            if level > 0: col_spacer, col_content = st.columns([0.5 * level, 10])
            else: col_content = st.container()
            with col_content:
                st.markdown(f"**{com['user']}**: {com['comment']}")
                if com['user'] == st.session_state.user:
                    c1, c2 = st.columns([0.5, 9.5])
                    with c1:
                        # KEY REMOVED FROM POPOVER TO FIX TYPEERROR
                        with st.popover("⋮"):
                            with st.expander("✏️ Edit"):
                                ed_txt = st.text_input("Edit", value=com['comment'], key=f"ed_com_{com['id']}")
                                if st.button("Save", key=f"sv_com_{com['id']}"): edit_item("comments", com['id'], ed_txt, "comment")
                            with st.expander("🗑️ Delete"):
                                st.warning("Delete this comment?")
                                if st.button("Confirm", key=f"del_c_{com['id']}"): delete_item("comments", com['id'])
                if level < 3: 
                    # KEY REMOVED FROM POPOVER
                    with st.popover("Reply"):
                        reply = st.text_input("Reply...", key=f"rp_{com['id']}")
                        if st.button("Post", key=f"bp_{com['id']}"): add_comment(target_id, target_type, st.session_state.user, reply, parent_id=com['id']); st.rerun()
                st.divider()
                render_comments(target_id, target_type, com['id'], level + 1)

def render_feed_item(note):
    with st.container(border=True):
        if note['post_type'] == "DOUBT": col_body = st.container()
        else:
            col_vote, col_body = st.columns([1, 10])
            with col_vote:
                st.metric("Votes", note['upvotes'])
                if st.button("⬆️", key=f"u_{note['id']}"): handle_vote(note['id'], "NOTE", st.session_state.user, 1); st.rerun()
                if st.button("⬇️", key=f"d_{note['id']}"): handle_vote(note['id'], "NOTE", st.session_state.user, -1); st.rerun()
        with col_body:
            c_title, c_meta = st.columns([8, 2])
            with c_title: st.subheader(f"{'❓' if note['post_type'] == 'DOUBT' else '📄'} {note['title']}")
            with c_meta:
                c_bm, c_opt = st.columns(2)
                with c_bm:
                    if st.button("🔖", key=f"bm_{note['id']}", help="Save"): toggle_bookmark(note['id'])
                with c_opt:
                    if note['uploader'] == st.session_state.user:
                        # KEY REMOVED FROM POPOVER
                        with st.popover("⋮"):
                            with st.expander("✏️ Edit Post"):
                                ed_ti = st.text_input("Title", value=note['title'], key=f"edt_{note['id']}")
                                ed_co = st.text_area("Content", value=note['content'], key=f"edc_{note['id']}")
                                if st.button("Update", key=f"upd_{note['id']}"): update_post(note['id'], ed_ti, ed_co)
                            with st.expander("🗑️ Delete Post"):
                                st.warning(f"Delete this {note['post_type'].title()}?")
                                if st.button("Confirm", key=f"del_{note['id']}"): delete_item("notes", note['id'])
                    else:
                        # KEY REMOVED FROM POPOVER
                        with st.popover("⋮"):
                            with st.expander("📤 Share"):
                                st.write("Copy Link:"); st.code(f"https://iitconnect.app/post/{note['id']}")
                                c1, c2 = st.columns(2)
                                c1.button("📱 Whatsapp"); c2.button("🐦 Twitter")
                            with st.expander("🚩 Report"):
                                reason = st.selectbox("Reason", ["Spam", "Harassment", "Hate Speech", "False Info", "Other"], key=f"rr_{note['id']}")
                                det = st.text_area("Details", key=f"rd_{note['id']}")
                                if st.button("Submit Report", key=f"sr_{note['id']}"):
                                    submit_report(note['id'], st.session_state.user, reason, det); st.success("Reported.")
            
            badge_info = ""
            if note['uploader'] != "Anonymous":
                udata = get_data("SELECT reputation FROM users WHERE username=?", (note['uploader'],))
                if udata: badge_info = f" • {get_user_badge(udata[0]['reputation'])}"

            if st.button(f"By **{note['uploader']}**{badge_info}", key=f"usr_lnk_{note['id']}", type="secondary"):
                if note['uploader'] != "Anonymous":
                    st.session_state.nav = "Profile_View"; st.session_state.view_user = note['uploader']; st.rerun()
            
            st.caption(f"in *{note['subject']}* • `{note['tags']}`")
            if note['post_type'] == "DOUBT": st.write(note['content'])
            
            if note['filename'] and note['filename'] != "DOUBT":
                fpath = os.path.join(UPLOAD_FOLDER, note['filename'])
                if os.path.exists(fpath):
                    ext = note['filename'].split('.')[-1].lower()
                    c1, c2 = st.columns([1, 1])
                    with c1:
                        if ext=='pdf': 
                            with st.expander("📄 View PDF"): pdf_viewer(fpath, height=400)
                        elif ext in ['png','jpg','jpeg']: st.image(fpath, width=400)
                    with c2:
                        with open(fpath, "rb") as f: st.download_button("⬇️ Download", f, file_name=note['filename'])
            st.divider()
            
            if note['post_type'] == "DOUBT":
                st.write("#### ✅ Answers")
                ans = get_data("SELECT * FROM answers WHERE doubt_id=? ORDER BY upvotes DESC", (note['id'],))
                for a in ans:
                    ac1, ac2 = st.columns([0.5, 9.5])
                    with ac1:
                        st.write(f"**{a['upvotes']}**")
                        if st.button("👍", key=f"au_{a['id']}"): handle_vote(a['id'], "ANSWER", st.session_state.user, 1); st.rerun()
                    with ac2:
                        st.write(f"**{a['responder']}**")
                        st.info(a['answer_text'])
                        if a['responder'] == st.session_state.user:
                             # KEY REMOVED FROM POPOVER
                             with st.popover("⋮"):
                                 with st.expander("✏️ Edit"):
                                     ed_ans = st.text_area("Edit Answer", value=a['answer_text'], key=f"eda_{a['id']}")
                                     if st.button("Save", key=f"sa_{a['id']}"): edit_item("answers", a['id'], ed_ans, "answer_text")
                                 with st.expander("🗑️ Delete"):
                                     st.warning("Delete this answer?")
                                     if st.button("Confirm", key=f"da_{a['id']}"): delete_item("answers", a['id'])
                        with st.expander("Comments"):
                            render_comments(a['id'], "ANSWER")
                            with st.form(f"cform_ans_{a['id']}"):
                                c_txt = st.text_input("Comment...", key=f"aci_{a['id']}")
                                if st.form_submit_button("Post"): add_comment(a['id'], "ANSWER", st.session_state.user, c_txt, item_owner=a['responder']); st.rerun()

                st.markdown("---")
                with st.form(f"na_form_{note['id']}"):
                    ans_txt = st.text_area("Write your answer...")
                    if st.form_submit_button("Post Answer"): 
                        add_answer(note['id'], st.session_state.user, ans_txt, note['uploader']); st.rerun()
            else:
                st.write("#### 💬 Discussion")
                render_comments(note['id'], "NOTE")
                with st.form(f"rc_form_{note['id']}"):
                    c_txt = st.text_input("Comment...")
                    if st.form_submit_button("Post"): add_comment(note['id'], "NOTE", st.session_state.user, c_txt, item_owner=note['uploader']); st.rerun()

# --- 8. MAIN APP ---
init_db()
if 'user' not in st.session_state: st.session_state.user = None
if 'err' not in st.session_state: st.session_state.err = None
if 'nav' not in st.session_state: st.session_state.nav = "Feed"
if 'view_user' not in st.session_state: st.session_state.view_user = None
if 'course_tab' not in st.session_state: st.session_state.course_tab = "Notes"
if 'chat_history' not in st.session_state: st.session_state.chat_history = []

if not st.session_state.user:
    st.title("IITConnect")
    t1, t2 = st.tabs(["Login", "Register"])
    with t1:
        u = st.text_input("Username"); p = st.text_input("Password", type="password")
        if st.button("Login", use_container_width=True): 
            if login_user(u, p): st.session_state.user = u; st.rerun()
            else: st.error("Invalid")
    with t2:
        u = st.text_input("New User"); p = st.text_input("New Pass", type="password"); c = st.text_input("College (Required)")
        if st.button("Sign Up", use_container_width=True):
            if c and u and p:
                if register_user(u, p, c): st.success("Created!");
                else: st.error("Taken.")
            else: st.error("Missing fields.")
else:
    # --- SIDEBAR ---
    with st.sidebar:
        user_data, _, _ = get_user_stats_detailed(st.session_state.user)
        # Profile Picture Button
        if user_data and user_data['profile_pic']:
            st.markdown(f"""
            <style>
                div[data-testid="stSidebar"] div[data-testid="element-container"]:nth-child(1) button {{
                    background-image: url("data:image/png;base64,{user_data['profile_pic']}");
                    background-size: cover;
                    background-position: center;
                    color: transparent !important;
                }}
            </style>
            """, unsafe_allow_html=True)
            if st.button("P", key="profile_btn", help="My Profile"): st.session_state.nav = "Profile"
        else:
            initial = st.session_state.user[0].upper()
            st.markdown(f"""<style>div[data-testid="stSidebar"] div[data-testid="element-container"]:nth-child(1) button {{ background-color: #ff5722 !important; }}</style>""", unsafe_allow_html=True)
            if st.button(initial, key="profile_btn"): st.session_state.nav = "Profile"
        
        st.markdown(f"<div style='text-align:center;margin-bottom:20px'><b>{st.session_state.user}</b></div>", unsafe_allow_html=True)
        
        if st.button("🔥 Campus Feed"): st.session_state.nav = "Feed"
        if st.button("📂 Course Folders"): st.session_state.nav = "Folders"
        if st.button("📝 Contribute"): st.session_state.nav = "Post"
        if st.button("🏆 Leaderboard"): st.session_state.nav = "Leaderboard"
        if st.button("⚡ Study Center"): st.session_state.nav = "Study Center"
        if st.button("🤖 AI Tutor"): st.session_state.nav = "AI Tutor"
        
        if st.session_state.user == "admin":
            st.markdown("---")
            if st.button("🔒 Admin Panel"): st.session_state.nav = "Admin"

        st.divider()
        if st.button("Logout"): st.session_state.user = None; st.rerun()
        
        with st.expander("📞 Contact Us"):
            st.markdown("""
            **Get in Touch:**
            📧 **Email:** contact@iitconnect.com
            📸 **Instagram:** [@iitconnect_official](https://instagram.com)
            📞 **Phone:** +91 98765 43210
            """)
    
    menu = st.session_state.nav

    # --- PAGES ---
    if menu == "AI Tutor":
        st.title("🤖 AI Tutor Chat")
        st.caption("Ask questions, get explanations, or debug code. (Not saved to database)")
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])
        if prompt := st.chat_input("Ask the tutor..."):
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    response = get_ai_model().generate_content(prompt).text
                    st.markdown(response)
                    st.session_state.chat_history.append({"role": "assistant", "content": response})
                except Exception as e: st.error(f"Error: {e}")

    elif menu == "Profile":
        st.title("👤 My Profile")
        if user_data:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Reputation", user_data['reputation'])
            c2.metric("Notes", get_user_stats_detailed(st.session_state.user)[2])
            c3.metric("Doubts", get_user_stats_detailed(st.session_state.user)[1])
            c4.metric("Answers", user_data['answers_count'])
            st.write("---")
            t_prof, t_saved = st.tabs(["Edit Profile", "🔖 Saved Items"])
            with t_prof:
                with st.form("prof_form"):
                    col_l, col_r = st.columns([1, 2])
                    with col_l:
                        if user_data['profile_pic']: st.image(base64.b64decode(user_data['profile_pic']), width=150)
                        new_pic = st.file_uploader("Change Picture", type=['png', 'jpg'])
                    with col_r:
                        fn = st.text_input("Full Name", value=user_data['full_name'] or "")
                        bio = st.text_area("Bio", value=user_data['bio'] or "")
                    c_y, c_b, c_a = st.columns(3)
                    with c_y: yr = st.text_input("Year", value=user_data['year'] or "")
                    with c_b: br = st.text_input("Branch", value=user_data['branch'] or "")
                    with c_a: age = st.text_input("Age", value=user_data['age'] or "")
                    if st.form_submit_button("💾 Save Profile"):
                        pic_data = user_data['profile_pic']
                        if new_pic: pic_data = base64.b64encode(new_pic.read()).decode('utf-8')
                        update_user_profile(st.session_state.user, fn, yr, br, age, user_data['gender'], bio, pic_data)
                        st.success("Updated!"); st.rerun()
                st.subheader("⚙️ Settings")
                with st.expander("Change Username"):
                    nu = st.text_input("New Username")
                    if st.button("Update Username"):
                        if change_username(st.session_state.user, nu): st.session_state.user=nu; st.success("Changed!"); st.rerun()
                        else: st.error("Taken.")
                c_del1, c_del2 = st.columns(2)
                with c_del1:
                    if st.button("Deactivate Account"): deactivate_account(st.session_state.user); st.session_state.user=None; st.rerun()
                with c_del2:
                    if not st.session_state.get('confirm_delete'):
                        if st.button("🗑️ Delete Account"): st.session_state.confirm_delete = True; st.rerun()
                    else:
                        st.error("⚠️ IRREVERSIBLE ACTION!")
                        if st.button("✅ Yes, Delete"): delete_account(st.session_state.user); st.session_state.user=None; st.rerun()
            with t_saved:
                bookmarks = get_data("SELECT * FROM notes WHERE id IN (SELECT note_id FROM bookmarks WHERE user=?)", (st.session_state.user,))
                if bookmarks:
                    for b in bookmarks: render_feed_item(b)
                else: st.info("No saved items yet.")

    elif menu == "Profile_View":
        target_user = st.session_state.view_user
        st.title(f"👤 {target_user}")
        if st.button("⬅ Back"): st.session_state.nav = "Feed"; st.rerun()
        tu_data, tu_doubts, tu_notes = get_user_stats_detailed(target_user)
        if tu_data:
            if tu_data['profile_pic']: st.image(base64.b64decode(tu_data['profile_pic']), width=150)
            st.write(f"**Bio:** {tu_data['bio'] or 'No bio.'}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Reputation", tu_data['reputation'])
            c2.metric("Contributions", tu_notes)
            c3.metric("Answers", tu_data['answers_count'])
        else: st.error("User not found.")

    elif menu == "Admin":
        st.title("🔒 Admin Panel")
        st.subheader("🚩 Reported Content")
        reports = get_data("SELECT * FROM reports ORDER BY timestamp DESC")
        if reports:
            st.dataframe(reports)
        else: st.success("No reports pending.")
        st.subheader("📚 Course Requests")
        reqs = get_data("SELECT * FROM course_requests ORDER BY timestamp DESC")
        if reqs: st.dataframe(reqs)
        else: st.info("No course requests.")

    elif menu == "Feed":
        c1, c2 = st.columns([9, 1])
        with c1: st.title("🔥 Campus Feed")
        with c2:
            notif_count, notifs = get_unread_notifications(st.session_state.user)
            icon = "🔔" if notif_count == 0 else f"🔔 {notif_count}"
            # KEY REMOVED FROM POPOVER
            with st.popover(icon):
                st.write("### Notifications")
                if notifs:
                    if st.button("Mark Read", key="mark_read_feed"): 
                        mark_notifications_read(st.session_state.user)
                        st.rerun()
                    for n in notifs: st.info(f"{n[2]} ({n[4]})")
                else: st.caption("No new notifications.")
        
        tags_raw = get_data("SELECT tags FROM notes")
        all_tags = []
        for t in tags_raw: all_tags.extend([x.strip() for x in t['tags'].split(',') if x.strip()])
        top_tags = [t[0] for t in Counter(all_tags).most_common(5)]
        st.write("Trending Topics:")
        cols = st.columns(len(top_tags) + 1)
        if cols[0].button("All"): st.session_state.tag_filter = None
        for i, tag in enumerate(top_tags):
            if cols[i+1].button(f"#{tag}"): st.session_state.tag_filter = tag
        q = st.text_input("🔍 Search...", placeholder="Tag, Title...")
        query = "SELECT * FROM notes"
        params = []
        if q:
            query += " WHERE (title LIKE ? OR tags LIKE ?)"
            params = [f"%{q}%", f"%{q}%"]
        elif getattr(st.session_state, 'tag_filter', None):
            query += " WHERE tags LIKE ?"
            params = [f"%{st.session_state.tag_filter}%"]
        query += " ORDER BY timestamp DESC"
        notes = get_data(query, params)
        for n in notes: render_feed_item(n)

    elif menu == "Folders":
        st.title("📂 Course Folders")
        st.markdown("""<style>div[data-testid="column"] div.stButton > button {height: 200px !important; width: 100% !important; aspect-ratio: 1/1 !important; border-radius: 20px !important; font-size: 22px !important; display: flex !important; flex-direction: column !important; align-items: center !important; justify-content: center !important; background: linear-gradient(145deg, #1e1e1e, #292929) !important; border: 1px solid #444 !important; box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important;}</style>""", unsafe_allow_html=True)
        
        with st.expander("➕ Request a New Course"):
            with st.form("req_course_form"):
                req_name = st.text_input("Course Name (e.g. Thermodynamics)")
                req_reason = st.text_area("Why do you need this course? (Optional)")
                if st.form_submit_button("Submit Request"):
                    if req_name:
                        submit_course_request(st.session_state.user, req_name, req_reason)
                        st.success("Request sent! Admin will review it.")
                    else: st.error("Please enter a course name.")

        f_search = st.text_input("🔍 Filter Courses...", placeholder="e.g. Physics")
        all_courses = ["Physics", "Mathematics", "CS", "Electronics"]
        filtered_courses = [c for c in all_courses if f_search.lower() in c.lower()]
        
        if 'folder' not in st.session_state: st.session_state.folder = None
        if not st.session_state.folder:
            cols = st.columns(3)
            for i, course in enumerate(filtered_courses):
                with cols[i % 3]:
                    if st.button(f"📁\n{course}", key=f"fld_{course}", use_container_width=True):
                        st.session_state.folder = course
                        st.rerun()
        else:
            if st.button("⬅ Back to Courses"): st.session_state.folder = None; st.rerun()
            st.subheader(f"📂 {st.session_state.folder}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("📄 NOTES", use_container_width=True, type="primary" if st.session_state.course_tab=="Notes" else "secondary"): st.session_state.course_tab = "Notes"
            with c2:
                if st.button("❓ DOUBTS", use_container_width=True, type="primary" if st.session_state.course_tab=="Doubts" else "secondary"): st.session_state.course_tab = "Doubts"
            st.divider()
            if st.session_state.course_tab == "Notes":
                for n in get_data("SELECT * FROM notes WHERE subject=? AND post_type='RESOURCE' ORDER BY timestamp DESC", (st.session_state.folder,)): render_feed_item(n)
            else:
                for n in get_data("SELECT * FROM notes WHERE subject=? AND post_type='DOUBT' ORDER BY timestamp DESC", (st.session_state.folder,)): render_feed_item(n)

    elif menu == "Post":
        st.title("📝 Contribute")
        t1, t2 = st.tabs(["Upload Note", "Ask Doubt"])
        with t1:
            with st.form("u"):
                ti=st.text_input("Title"); sub=st.selectbox("Subject", ["Physics", "Mathematics", "CS", "Electronics"]); tags=st.text_input("Tags"); f=st.file_uploader("PDF", type="pdf")
                if st.form_submit_button("Upload"):
                    p = os.path.join(UPLOAD_FOLDER, f.name); open(p, "wb").write(f.getbuffer())
                    with st.spinner("AI Checking..."): v, r = verify_content_with_ai(get_pdf_text(p), sub)
                    if v: add_note(st.session_state.user, sub, ti, f.name, tags, True); st.success("Posted!")
                    else: st.session_state.err = f"Rejected: {r}"; st.rerun()
        with t2:
            with st.form("d"):
                ti=st.text_input("Question"); sub=st.selectbox("Sub", ["Physics", "Mathematics", "CS", "Electronics"], key="ds"); tags=st.text_input("Tags"); txt=st.text_area("Details")
                anon = st.checkbox("Ask Anonymously")
                if st.form_submit_button("Post Doubt"):
                    uploader_name = "Anonymous" if anon else st.session_state.user
                    add_note(uploader_name, sub, ti, "DOUBT", tags, True, content=txt, post_type="DOUBT")
                    st.success("Posted!")

    elif menu == "Leaderboard":
        st.title("🏆 Hall of Fame")
        data = get_data("SELECT username, posts_count, answers_count, reputation FROM users WHERE reputation > 0 ORDER BY reputation DESC LIMIT 10")
        df = pd.DataFrame(data, columns=["Name", "Contributions", "Answers Given", "Reputation Score"])
        df['Badge'] = df['Reputation Score'].apply(get_user_badge)
        st.dataframe(df, hide_index=True, use_container_width=True)

    elif menu == "Study Center":
        st.title("⚡ AI Study Center")
        if 'study_mode_sel' not in st.session_state: st.session_state.study_mode_sel = None

        if st.session_state.study_mode_sel is None:
            st.markdown("""<style>div[data-testid="column"] div.stButton > button {height: 200px !important; width: 100% !important; aspect-ratio: 1/1 !important; border-radius: 20px !important; font-size: 22px !important; display: flex !important; flex-direction: column !important; align-items: center !important; justify-content: center !important; background: linear-gradient(145deg, #1e1e1e, #292929) !important; border: 1px solid #444 !important; box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important;}</style>""", unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("📝\nPractice Questions", use_container_width=True): st.session_state.study_mode_sel = "Practice"
            with c2:
                if st.button("🧠\nStudy Tools", use_container_width=True): st.session_state.study_mode_sel = "Tools"
        else:
            if st.button("⬅ Back to Menu"): st.session_state.study_mode_sel = None; st.session_state.study_data = None; st.rerun()
            st.divider()
            
            file_path = None
            force_vision = st.checkbox("Force Vision (For scanned files)")
            src = st.radio("Source:", ["Library", "Upload"], horizontal=True)
            if src == "Library":
                sub = st.selectbox("Subject", ["Physics", "Mathematics", "CS", "Electronics"])
                notes = get_data("SELECT * FROM notes WHERE subject=? AND post_type='RESOURCE'", (sub,))
                if notes:
                    sel = st.selectbox("Material", [n['title'] for n in notes])
                    file_path = os.path.join(UPLOAD_FOLDER, next(n for n in notes if n['title'] == sel)['filename'])
            else:
                up = st.file_uploader("Upload PDF", type="pdf")
                if up:
                    temp = os.path.join(UPLOAD_FOLDER, f"temp_{datetime.now().strftime('%S')}.pdf"); open(temp, "wb").write(up.getbuffer()); file_path = temp

            if file_path:
                if st.session_state.study_mode_sel == "Practice":
                    t1, t2 = st.tabs(["MCQ", "Subjective"])
                    with t1:
                        if st.button("Generate MCQs"):
                            with st.spinner("Generating..."):
                                st.session_state.study_data = generate_ai_content(file_path, "mcq", force_vision)
                                st.session_state.quiz_answers = {}
                        if st.session_state.study_data and isinstance(st.session_state.study_data, list) and "options" in st.session_state.study_data[0]:
                            for i, q in enumerate(st.session_state.study_data):
                                st.markdown(f"**Q{i+1}: {q['question']}**")
                                st.session_state.quiz_answers[i] = st.radio("Select:", q['options'], key=f"mq_{i}", index=None)
                                st.divider()
                            if st.button("📝 Submit Quiz"):
                                score = 0
                                for i, q in enumerate(st.session_state.study_data):
                                    u_ans = st.session_state.quiz_answers.get(i)
                                    if u_ans and u_ans.strip() == q['answer'].strip(): score += 1
                                    else: st.error(f"Q{i+1}: Incorrect. Answer: {q['answer']}")
                                st.balloons(); st.success(f"Final Score: {score} / {len(st.session_state.study_data)}")
                    with t2:
                        if st.button("Generate Subjective"):
                            with st.spinner("Generating..."): st.session_state.study_data = generate_ai_content(file_path, "subjective", force_vision)
                        if st.session_state.study_data and isinstance(st.session_state.study_data, list) and "model_answer" in st.session_state.study_data[0]:
                            for i, q in enumerate(st.session_state.study_data):
                                st.write(f"**Q{i+1}: {q['question']}**"); 
                                if st.button(f"Show Answer {i+1}"): st.success(q['model_answer'])
                                st.divider()
                elif st.session_state.study_mode_sel == "Tools":
                    t1, t2 = st.tabs(["Summary", "Flashcards"])
                    with t1:
                        if st.button("Summarize"):
                            with st.spinner("Reading..."): st.session_state.study_data = generate_ai_content(file_path, "summary", force_vision)
                        if st.session_state.study_data and isinstance(st.session_state.study_data, str): st.markdown(st.session_state.study_data)
                    with t2:
                        if st.button("Make Flashcards"):
                            with st.spinner("Thinking..."): st.session_state.study_data = generate_ai_content(file_path, "flashcard", force_vision)
                        if st.session_state.study_data and isinstance(st.session_state.study_data, list) and "term" in st.session_state.study_data[0]:
                            c1, c2 = st.columns(2)
                            for i, c in enumerate(st.session_state.study_data):
                                with (c1 if i%2==0 else c2):
                                    with st.container(border=True):
                                        st.markdown(f"### {c['term']}")
                                        with st.expander("Reveal"): st.info(c['definition'])