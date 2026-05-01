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
 
# 2. Deploy the Reasoning Engine
print("Deploying Agent Engine to Vertex AI...")
 
agent_engine = reasoning_engines.ReasoningEngine.create(
    PlutusAgentEngine(),
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
    ],
    display_name="Plutus-AI"
)
 
# 3. Output the Engine ID for your Frontend
print(f"Deployment complete! Your AGENT_ENGINE_ID is: {agent_engine.resource_name}")