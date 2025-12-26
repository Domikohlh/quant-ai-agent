# test_model_connection.py
import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI

credentials, project_id = google.auth.default()

model_type = ["gemini-2.5-flash", "gemini-2.5-pro","gemini-2.5-flash-lite" ]

for model in model_type:
  # Try the stable 1.5 Pro model
  llm = ChatGoogleGenerativeAI(
    model=model,
    project=project_id,
    location="us-central1",
    credentials=credentials
  )

  try:
     print(f'Currently testing: {model}')
     print("Testing connection to Vertex AI...")
     response = llm.invoke("Hello, are you online?")
     print(f"✅ SUCCESS: {response.content}")
  except Exception as e:
     print(f"❌ ERROR: {e}")
