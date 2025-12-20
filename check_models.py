import google.generativeai as genai

# --- PASTE YOUR GEMINI API KEY HERE ---
GEMINI_API_KEY = "AIzaSyB5QPNOt0s_9iKnawAIa8zzSb4yNr6KQ8k"

genai.configure(api_key=GEMINI_API_KEY)

print("Checking available models...")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
except Exception as e:
    print(f"Error: {e}")