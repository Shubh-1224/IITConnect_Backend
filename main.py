from fastapi import FastAPI, UploadFile, File, HTTPException
from supabase import create_client, Client
import google.generativeai as genai
import shutil
import os

app = FastAPI()

# --- CONFIGURATION ---
# 1. PASTE YOUR SUPABASE KEYS HERE
SUPABASE_URL = "https://wfebnvlyekxaxkmbizpe.supabase.co" 
SUPABASE_KEY = "sb_publishable_kr7GtIk14s2PaxFTaDsoWg_EAI47U0v"

# 2. PASTE YOUR GEMINI API KEY HERE
# (Get one here if you don't have it: https://aistudio.google.com/app/apikey)
GEMINI_API_KEY = "AIzaSyB5QPNOt0s_9iKnawAIa8zzSb4yNr6KQ8k"

# Initialize connections
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

@app.get("/")
def read_root():
    return {"message": "CourseHive Backend is Online!"}

# --- THE AI VERIFICATION ENGINE ---
@app.post("/verify-upload/")
async def verify_upload(course_name: str, file: UploadFile = File(...)):
    
    # 1. Save file temporarily so we can read it
    temp_filename = f"temp_{file.filename}"
    with open(temp_filename, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # 2. Upload to Gemini for analysis
        # (Gemini Pro 1.5 can read files directly!)
        print("Sending to AI...")
        uploaded_file = genai.upload_file(path=temp_filename)
        model = genai.GenerativeModel('gemini-flash-latest')
        # 3. Ask the AI the big questions
        prompt = f"""
        Analyze this document. It is uploaded for the college course: {course_name}.
        Answer in this exact format:
        IS_RELEVANT: [YES/NO]
        IS_LEGITIMATE: [YES/NO]
        SUMMARY: [One sentence summary]
        """
        
        response = model.generate_content([prompt, uploaded_file])
        print(f"AI Verdict: {response.text}")
        
        # 4. Cleanup
        os.remove(temp_filename)

        return {"ai_response": response.text}

    except Exception as e:
        return {"error": str(e)}