import vertexai
from google.cloud import aiplatform
from vertexai.preview import reasoning_engines
from agent import PlutusAgentEngine
 
# 1. Initialize Vertex AI
aiplatform.init(
    project="",
    location="us-central1",
    service_account=""
)
 
vertexai.init(
    project="",
    location="us-central1",
    staging_bucket=""
)
 
print("Updating Existing AgentEngine on Vertex AI...")
 
# 2. Add your EXACT existing Agent Engine ID here
# (You should be able to find this in your Vertex AI Console or past deployment logs)
EXISTING_ENGINE_ID = ""
 
# 3. Bind to the existing Engine
agent_engine = reasoning_engines.ReasoningEngine(EXISTING_ENGINE_ID)
 
# 4. Use .update() instead of .create()!
agent_engine.update(
    reasoning_engine=PlutusAgentEngine(),
    requirements=[
        "google-adk",
        "google-cloud-aiplatform[reasoningengine]",
        "google-genai",
        "mcp",
        "toolbox-core",
        "requests",
        "uv",
        "fakeredis"
    ],
    extra_packages=[
        "."
    ]
)
 
print(f"Update complete! Your AGENT_ENGINE_ID remains: {agent_engine.resource_name}")
