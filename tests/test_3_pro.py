# test_gemini_3.py
import os
import google.auth
from google import genai
from google.genai import types

# 1. Authenticate
creds, project_id = google.auth.default()

# 2. Initialize Client with "global" location
# CRITICAL: Gemini 3.0 Preview is NOT in us-central1 yet. It is in 'global'.
client = genai.Client(
    vertexai=True,
    project=project_id,
    location="global"  # <--- CHANGE THIS FROM 'us-central1'
)

model_id = "gemini-3-pro-preview"

print(f"Testing {model_id} on GLOBAL endpoint...")

try:
    response = client.models.generate_content(
        model=model_id,
        contents="Explain quantum entanglement to a 5 year old.",
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_level="HIGH"
            )
        )
    )
    print(f"✅ SUCCESS:\n{response.text}")

except Exception as e:
    print(f"❌ ERROR: {e}")
