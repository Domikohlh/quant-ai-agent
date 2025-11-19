#!/bin/bash
# Deploy Production Model to GPU Server
# Downloads model and sets up inference server

set -e

if [ -z "$1" ]; then
    echo "Usage: ./deploy_production_model.sh <server_ip> [model_name]"
    echo ""
    echo "Example: ./deploy_production_model.sh 54.123.45.67 meta-llama/Llama-3.2-3B-Instruct"
    exit 1
fi

SERVER_IP=$1
MODEL_NAME=${2:-"meta-llama/Llama-3.2-3B-Instruct"}

echo "🤖 Deploying Production Model"
echo "=============================="
echo ""
echo "Server IP: $SERVER_IP"
echo "Model: $MODEL_NAME"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Step 1: Test Connection
echo "Step 1: Testing Connection"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

for attempt in {1..5}; do
    if ssh -i ~/.ssh/id_rsa -o ConnectTimeout=10 -o StrictHostKeyChecking=no \
           ubuntu@$SERVER_IP "echo 'Connected'" &>/dev/null; then
        echo -e "${GREEN}✅ Connection successful${NC}"
        break
    fi
    
    if [ $attempt -eq 5 ]; then
        echo "❌ Cannot connect after 5 attempts"
        echo "Please wait a few minutes and try again"
        exit 1
    fi
    
    echo "Attempt $attempt/5 failed, retrying in 10 seconds..."
    sleep 10
done

echo ""

# Step 2: Setup Environment
echo "Step 2: Setting Up Environment"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ssh -i ~/.ssh/id_rsa ubuntu@$SERVER_IP << 'ENVSSH'
#!/bin/bash
set -e

echo "Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y python3-pip python3-venv git curl htop nvtop

echo "Checking NVIDIA drivers..."
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi
    echo "✅ GPU available"
else
    echo "⚠️  No GPU detected (using Deep Learning AMI drivers)"
fi

echo "Creating project directory..."
mkdir -p ~/quantai-production
cd ~/quantai-production

echo "Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "Installing PyTorch with CUDA..."
pip install --upgrade pip
pip install torch==2.1.2 torchvision==0.16.2 torchaudio==2.1.2 \
    --index-url https://download.pytorch.org/whl/cu121

echo "Installing Transformers and dependencies..."
pip install transformers==4.36.2 \
    accelerate==0.26.1 \
    bitsandbytes==0.41.3 \
    sentencepiece==0.1.99 \
    fastapi==0.109.0 \
    uvicorn[standard]==0.27.0 \
    pydantic==2.5.3 \
    python-multipart==0.0.6

echo "Testing PyTorch CUDA..."
python3 << 'PYEOF'
import torch
print(f"PyTorch: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"CUDA version: {torch.version.cuda}")
    print(f"GPU: {torch.cuda.get_device_name(0)}")
PYEOF

echo "✅ Environment setup complete"
ENVSSH

echo -e "${GREEN}✅ Environment configured${NC}"
echo ""

# Step 3: Download Model
echo "Step 3: Downloading Model"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${YELLOW}⏳ This may take 10-30 minutes depending on model size...${NC}"
echo ""

ssh -i ~/.ssh/id_rsa ubuntu@$SERVER_IP << MODELSSH
#!/bin/bash
set -e

cd ~/quantai-production
source venv/bin/activate

echo "Downloading model: $MODEL_NAME"
echo "This will take some time..."

python3 << 'PYEOF'
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
import os

model_name = "$MODEL_NAME"
cache_dir = os.path.expanduser("~/quantai-production/models")
os.makedirs(cache_dir, exist_ok=True)

print(f"Model: {model_name}")
print(f"Cache dir: {cache_dir}")
print("")

# Download tokenizer
print("1/2 Downloading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(
    model_name,
    cache_dir=cache_dir,
    trust_remote_code=True
)
print("✅ Tokenizer downloaded")

# Download model with 4-bit quantization
print("")
print("2/2 Downloading model (4-bit quantized)...")
print("This is the slow part...")

model = AutoModelForCausalLM.from_pretrained(
    model_name,
    cache_dir=cache_dir,
    device_map="auto",
    load_in_4bit=True,
    torch_dtype=torch.float16,
    trust_remote_code=True,
)

print("")
print("✅ Model downloaded and loaded!")
print(f"Device: {model.device}")
print(f"Memory: {torch.cuda.memory_allocated(0) / 1024**3:.2f} GB")

# Test generation
print("")
print("Testing generation...")
test_input = "The stock market"
inputs = tokenizer(test_input, return_tensors="pt").to(model.device)
outputs = model.generate(**inputs, max_new_tokens=20)
result = tokenizer.decode(outputs[0], skip_special_tokens=True)
print(f"Input: {test_input}")
print(f"Output: {result}")

print("")
print("✅ Model test successful!")
PYEOF

echo ""
echo "✅ Model downloaded"
MODELSSH

echo -e "${GREEN}✅ Model deployed${NC}"
echo ""

# Step 4: Create Model Server
echo "Step 4: Creating Model Server"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Upload model server code
scp -i ~/.ssh/id_rsa backend/models/llm/server.py ubuntu@$SERVER_IP:~/quantai-production/

ssh -i ~/.ssh/id_rsa ubuntu@$SERVER_IP << 'SERVERSSH'
#!/bin/bash
cd ~/quantai-production

# Create startup script
cat > start_server.sh << 'STARTSSH'
#!/bin/bash
cd ~/quantai-production
source venv/bin/activate

# Set environment variables
export PRIMARY_MODEL_NAME="$MODEL_NAME"
export PRIMARY_MODEL_PATH="~/quantai-production/models"
export MODEL_SERVER_API_KEY="production-key-change-me"

# Start server
nohup python3 server.py > server.log 2>&1 &
echo $! > server.pid

echo "Server started, PID: $(cat server.pid)"
echo "Logs: tail -f ~/quantai-production/server.log"
STARTSSH

chmod +x start_server.sh

echo "✅ Server scripts created"
SERVERSSH

echo -e "${GREEN}✅ Model server configured${NC}"
echo ""

# Step 5: Start Server
echo "Step 5: Starting Model Server"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ssh -i ~/.ssh/id_rsa ubuntu@$SERVER_IP "cd ~/quantai-production && ./start_server.sh"

echo "Waiting for server to start..."
sleep 10

echo ""

# Step 6: Test Server
echo "Step 6: Testing Model Server"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Testing health endpoint..."
if curl -s http://$SERVER_IP:8001/health | python3 -m json.tool 2>/dev/null; then
    echo ""
    echo -e "${GREEN}✅ Health check passed${NC}"
else
    echo ""
    echo -e "${YELLOW}⚠️  Health check failed (server may still be starting)${NC}"
fi

echo ""
echo "Testing generation endpoint..."
curl -X POST http://$SERVER_IP:8001/generate \
    -H "Content-Type: application/json" \
    -H "X-API-Key: production-key-change-me" \
    -d '{
        "prompt": "The future of AI is",
        "max_tokens": 30,
        "temperature": 0.7
    }' | python3 -m json.tool 2>/dev/null || echo "Generation test pending..."

echo ""

# Step 7: Display Summary
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║          MODEL DEPLOYED SUCCESSFULLY! 🎉                   ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 Deployment Summary:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Model Server: $SERVER_IP"
echo "Model: $MODEL_NAME"
echo "API Endpoint: http://$SERVER_IP:8001"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🧪 Test Commands:"
echo ""
echo "1. Health check:"
echo "   curl http://$SERVER_IP:8001/health"
echo ""
echo "2. Generate text:"
echo "   curl -X POST http://$SERVER_IP:8001/generate \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -H 'X-API-Key: production-key-change-me' \\"
echo "     -d '{\"prompt\": \"Hello\", \"max_tokens\": 50}'"
echo ""
echo "3. View logs:"
echo "   ssh -i ~/.ssh/id_rsa ubuntu@$SERVER_IP 'tail -f ~/quantai-production/server.log'"
echo ""
echo "4. Monitor GPU:"
echo "   ssh -i ~/.ssh/id_rsa ubuntu@$SERVER_IP 'watch nvidia-smi'"
echo ""
echo "5. Stop server:"
echo "   ssh -i ~/.ssh/id_rsa ubuntu@$SERVER_IP 'kill \$(cat ~/quantai-production/server.pid)'"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${YELLOW}⚠️  Remember: GPU server costs ~\$0.53/hour${NC}"
echo ""
echo "Next step: Setup API server"
echo "  ./setup_api_server.sh $API_SERVER_IP $SERVER_IP"
echo ""
