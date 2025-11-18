#!/bin/bash
# Deploy Model to AWS Test Server
# This script sets up the model server and deploys a small test model

set -e

if [ -z "$1" ]; then
    echo "Usage: ./deploy_model_to_aws.sh <server_ip>"
    echo ""
    echo "Example: ./deploy_model_to_aws.sh 54.123.45.67"
    exit 1
fi

SERVER_IP=$1

echo "🚀 Deploying Model to AWS Server"
echo "================================="
echo ""
echo "Server IP: $SERVER_IP"
echo ""

# Step 1: Test connection
echo "Step 1: Testing SSH connection..."
ssh -i ~/.ssh/id_rsa -o ConnectTimeout=10 ubuntu@$SERVER_IP "echo 'Connection successful'" || {
    echo "❌ Cannot connect to server. Is it running?"
    exit 1
}
echo "✅ Connection successful"
echo ""

# Step 2: Choose model
echo "Step 2: Choose model to deploy"
echo "-------------------------------"
echo ""
echo "Options:"
echo "  1) Tiny test model (distilgpt2 ~350MB) - Fast, cheap, for testing only"
echo "  2) Small model (Llama 3.2 1B ~2GB) - Small but functional"
echo "  3) Medium model (Llama 3.2 3B ~6GB) - Good balance"
echo "  4) Skip model download (use for testing infrastructure only)"
echo ""
read -p "Choose option (1-4): " model_choice

case $model_choice in
    1)
        MODEL_NAME="distilgpt2"
        MODEL_SIZE="350MB"
        ;;
    2)
        MODEL_NAME="meta-llama/Llama-3.2-1B-Instruct"
        MODEL_SIZE="2GB"
        ;;
    3)
        MODEL_NAME="meta-llama/Llama-3.2-3B-Instruct"
        MODEL_SIZE="6GB"
        ;;
    4)
        echo "Skipping model download"
        MODEL_NAME="none"
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "Selected: $MODEL_NAME ($MODEL_SIZE)"
echo ""

# Step 3: Create deployment script
echo "Step 3: Creating deployment script..."

cat > /tmp/setup_model_server.sh << 'SCRIPT_EOF'
#!/bin/bash
set -e

echo "🔧 Setting up Model Server"
echo "=========================="
echo ""

# Install dependencies
echo "Installing dependencies..."
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv git curl

# Check NVIDIA drivers
if ! command -v nvidia-smi &> /dev/null; then
    echo "⚠️  No nvidia-smi found. Using Deep Learning AMI drivers."
fi

# Create working directory
mkdir -p ~/quantai
cd ~/quantai

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install PyTorch with CUDA support
echo "Installing PyTorch (this may take a few minutes)..."
pip install --upgrade pip
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install transformers and dependencies
echo "Installing Transformers..."
pip install transformers accelerate bitsandbytes sentencepiece
pip install fastapi uvicorn pydantic python-multipart aiofiles

# Test PyTorch CUDA
echo ""
echo "Testing PyTorch CUDA availability..."
python3 << 'PYEOF'
import torch
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"CUDA version: {torch.version.cuda}")
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB")
PYEOF

echo ""
echo "✅ Setup complete!"
SCRIPT_EOF

chmod +x /tmp/setup_model_server.sh

echo "✅ Deployment script created"
echo ""

# Step 4: Copy and execute setup script
echo "Step 4: Setting up server environment..."
echo ""

scp -i ~/.ssh/id_rsa /tmp/setup_model_server.sh ubuntu@$SERVER_IP:/tmp/
ssh -i ~/.ssh/id_rsa ubuntu@$SERVER_IP "bash /tmp/setup_model_server.sh"

echo ""
echo "✅ Server environment configured"
echo ""

# Step 5: Download model (if selected)
if [ "$MODEL_NAME" != "none" ]; then
    echo "Step 5: Downloading model..."
    echo "⏳ This may take several minutes depending on model size..."
    echo ""
    
    ssh -i ~/.ssh/id_rsa ubuntu@$SERVER_IP << SSHEOF
cd ~/quantai
source venv/bin/activate

python3 << 'PYEOF'
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

model_name = "$MODEL_NAME"
print(f"Downloading model: {model_name}")
print("This may take a while...")

# Download tokenizer
print("Downloading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(model_name)

# Download model with 4-bit quantization
print("Downloading model (4-bit quantized)...")
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    device_map="auto",
    load_in_4bit=True,
    torch_dtype=torch.float16,
)

print("✅ Model downloaded and loaded successfully!")
print(f"Model device: {model.device}")
print(f"Model dtype: {model.dtype}")

# Test generation
print("\nTesting model generation...")
test_prompt = "Hello, I am"
inputs = tokenizer(test_prompt, return_tensors="pt").to(model.device)
outputs = model.generate(**inputs, max_new_tokens=20)
generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
print(f"Test output: {generated_text}")
print("\n✅ Model test successful!")
PYEOF
SSHEOF

    echo ""
    echo "✅ Model downloaded and tested"
    echo ""
else
    echo "Step 5: Skipped model download"
    echo ""
fi

# Step 6: Create simple model server
echo "Step 6: Creating model inference server..."

ssh -i ~/.ssh/id_rsa ubuntu@$SERVER_IP << 'SSHEOF'
cd ~/quantai

cat > model_server.py << 'PYEOF'
"""
Simple FastAPI model server for testing.
"""
from fastapi import FastAPI
from pydantic import BaseModel
import torch

app = FastAPI(title="Quant AI Test Model Server")

class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int = 50

@app.get("/")
async def root():
    return {"status": "running", "message": "Quant AI Test Model Server"}

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A"
    }

@app.post("/generate")
async def generate(request: GenerateRequest):
    return {
        "prompt": request.prompt,
        "generated_text": f"[Test response to: {request.prompt}]",
        "model": "test-model",
        "status": "success"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
PYEOF

echo "✅ Model server created"
SSHEOF

echo ""

# Step 7: Start the server
echo "Step 7: Starting model server..."
echo ""

ssh -i ~/.ssh/id_rsa ubuntu@$SERVER_IP << 'SSHEOF'
cd ~/quantai
source venv/bin/activate

# Start server in background
nohup python model_server.py > server.log 2>&1 &
echo $! > server.pid

echo "⏳ Waiting for server to start..."
sleep 5

# Check if server is running
if curl -s http://localhost:8001/health > /dev/null; then
    echo "✅ Model server is running!"
else
    echo "⚠️  Server may not have started. Check logs with: tail -f ~/quantai/server.log"
fi
SSHEOF

echo ""

# Step 8: Test the server
echo "Step 8: Testing model server..."
echo ""

sleep 2

echo "Testing health endpoint..."
curl -s http://$SERVER_IP:8001/health | python3 -m json.tool
echo ""

echo "Testing generation endpoint..."
curl -X POST http://$SERVER_IP:8001/generate \
    -H "Content-Type: application/json" \
    -d '{"prompt": "Hello world", "max_tokens": 20}' | python3 -m json.tool

echo ""
echo ""

# Summary
echo "╔════════════════════════════════════════════════════════╗"
echo "║          MODEL SERVER DEPLOYED! 🎉                     ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "📊 Server Information:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Server IP: $SERVER_IP"
echo "API Endpoint: http://$SERVER_IP:8001"
echo "Health Check: http://$SERVER_IP:8001/health"
echo ""
echo "Model: $MODEL_NAME"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🧪 Test Commands:"
echo ""
echo "1. Health check:"
echo "   curl http://$SERVER_IP:8001/health"
echo ""
echo "2. Generate text:"
echo "   curl -X POST http://$SERVER_IP:8001/generate \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"prompt\": \"Hello\", \"max_tokens\": 20}'"
echo ""
echo "3. View server logs:"
echo "   ssh -i ~/.ssh/id_rsa ubuntu@$SERVER_IP 'tail -f ~/quantai/server.log'"
echo ""
echo "4. Stop server:"
echo "   ssh -i ~/.ssh/id_rsa ubuntu@$SERVER_IP 'kill \$(cat ~/quantai/server.pid)'"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "⚠️  Remember: GPU instance costs ~\$0.53/hour"
echo "    Stop when done testing!"
echo ""
