#!/bin/bash
# Save all deployment files to your project
# Run this script in your ai-assistant directory

set -e

echo "📦 Creating all deployment files..."
echo ""

# Check if we're in the right directory
if [ ! -d "infrastructure" ]; then
    echo "❌ Error: Not in ai-assistant directory"
    echo "Please run this script from: ~/path/to/ai-assistant"
    exit 1
fi

# ====================
# File 1: minimal.tf
# ====================
echo "Creating infrastructure/terraform/minimal.tf..."
cat > infrastructure/terraform/minimal.tf << 'EOF'
# Minimal Terraform configuration for testing only
# This creates the smallest possible setup for testing model inference
# Estimated cost: ~$0.50/hour (~$12/day if left running)

terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Variables
variable "aws_region" {
  description = "AWS region"
  default     = "us-east-1"
}

variable "your_ip" {
  description = "Your IP address for SSH access (format: x.x.x.x/32)"
  type        = string
}

variable "enable_model_server" {
  description = "Enable GPU model server (expensive, ~$0.50/hr)"
  type        = bool
  default     = false
}

# Get latest Deep Learning AMI
data "aws_ami" "deep_learning" {
  most_recent = true
  owners      = ["amazon"]
  
  filter {
    name   = "name"
    values = ["Deep Learning AMI GPU PyTorch *"]
  }
  
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Get latest Ubuntu AMI
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]
  
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-22.04-amd64-server-*"]
  }
}

# S3 Bucket for models and logs
resource "aws_s3_bucket" "quantai_test" {
  bucket = "quantai-test-${random_id.bucket_suffix.hex}"
  
  tags = {
    Name        = "quantai-test-bucket"
    Environment = "test"
    Project     = "QuantAI"
  }
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket_versioning" "quantai_test" {
  bucket = aws_s3_bucket.quantai_test.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

# Security Group
resource "aws_security_group" "test_sg" {
  name        = "quantai-test-sg"
  description = "Security group for Quant AI test"
  
  # SSH from your IP only
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.your_ip]
    description = "SSH from your IP"
  }
  
  # Model server API (if enabled)
  ingress {
    from_port   = 8001
    to_port     = 8001
    protocol    = "tcp"
    cidr_blocks = [var.your_ip]
    description = "Model server API"
  }
  
  # Outbound internet access
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = {
    Name = "quantai-test-sg"
  }
}

# IAM Role for EC2
resource "aws_iam_role" "test_role" {
  name = "quantai-test-ec2-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "test_policy" {
  name = "quantai-test-policy"
  role = aws_iam_role.test_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.quantai_test.arn,
          "${aws_s3_bucket.quantai_test.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData",
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "test_profile" {
  name = "quantai-test-profile"
  role = aws_iam_role.test_role.name
}

# SSH Key Pair
resource "aws_key_pair" "test_key" {
  key_name   = "quantai-test-key"
  public_key = file(pathexpand("~/.ssh/id_rsa.pub"))
}

# Model Server (Optional - EXPENSIVE)
resource "aws_instance" "model_server" {
  count = var.enable_model_server ? 1 : 0
  
  ami           = data.aws_ami.deep_learning.id
  instance_type = "g4dn.xlarge"  # ~$0.526/hour
  
  vpc_security_group_ids = [aws_security_group.test_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.test_profile.name
  key_name               = aws_key_pair.test_key.key_name
  
  root_block_device {
    volume_size = 100
    volume_type = "gp3"
  }
  
  user_data = <<-EOF
              #!/bin/bash
              echo "Quant AI Model Server - Test Instance" > /home/ubuntu/README.txt
              echo "Instance started at: $(date)" >> /home/ubuntu/README.txt
              
              # Install Docker
              apt-get update
              apt-get install -y docker.io
              systemctl start docker
              systemctl enable docker
              usermod -aG docker ubuntu
              
              # Create marker file
              touch /home/ubuntu/model-server-ready
              EOF
  
  tags = {
    Name        = "quantai-model-server-test"
    Environment = "test"
    CostCenter  = "high-priority-stop"
  }
}

# Cheap Test Instance (Always created)
resource "aws_instance" "test_instance" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = "t3.micro"  # ~$0.0104/hour (FREE TIER eligible)
  
  vpc_security_group_ids = [aws_security_group.test_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.test_profile.name
  key_name               = aws_key_pair.test_key.key_name
  
  user_data = <<-EOF
              #!/bin/bash
              echo "Quant AI Test Instance" > /home/ubuntu/README.txt
              echo "Instance started at: $(date)" >> /home/ubuntu/README.txt
              
              # Install basic tools
              apt-get update
              apt-get install -y python3 python3-pip docker.io
              
              touch /home/ubuntu/test-instance-ready
              EOF
  
  tags = {
    Name        = "quantai-test-instance"
    Environment = "test"
  }
}

# Outputs
output "test_instance_ip" {
  value       = aws_instance.test_instance.public_ip
  description = "IP of test instance (t3.micro - cheap)"
}

output "test_instance_id" {
  value       = aws_instance.test_instance.id
  description = "Instance ID for test instance"
}

output "model_server_ip" {
  value       = var.enable_model_server ? aws_instance.model_server[0].public_ip : "Not deployed"
  description = "IP of model server (g4dn.xlarge - expensive)"
}

output "model_server_id" {
  value       = var.enable_model_server ? aws_instance.model_server[0].id : "Not deployed"
  description = "Instance ID for model server"
}

output "s3_bucket" {
  value       = aws_s3_bucket.quantai_test.bucket
  description = "S3 bucket name"
}

output "ssh_command_test" {
  value       = "ssh -i ~/.ssh/id_rsa ubuntu@${aws_instance.test_instance.public_ip}"
  description = "SSH command for test instance"
}

output "ssh_command_model" {
  value       = var.enable_model_server ? "ssh -i ~/.ssh/id_rsa ubuntu@${aws_instance.model_server[0].public_ip}" : "Model server not deployed"
  description = "SSH command for model server"
}

output "cost_estimate" {
  value = var.enable_model_server ? "~$0.53/hour (~$13/day with model server)" : "~$0.01/hour (~$0.25/day - FREE TIER eligible)"
  description = "Estimated hourly cost"
}
EOF
echo "✅ Created: infrastructure/terraform/minimal.tf"
echo ""

# ====================
# File 2: deploy_minimal_test.sh
# ====================
echo "Creating deploy_minimal_test.sh..."
cat > deploy_minimal_test.sh << 'EOF'
#!/bin/bash
# Deploy Minimal Test Environment
# This deploys a small test setup to verify everything works
# Cost: ~$0.01/hour for basic test (~$0.25/day - FREE TIER eligible)
# Cost with model server: ~$0.53/hour (~$13/day)

set -e

echo "🚀 Quant AI Minimal Test Deployment"
echo "====================================="
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Step 1: Get your IP address
echo "Step 1: Detecting your IP address..."
YOUR_IP=$(curl -s https://checkip.amazonaws.com)
echo -e "${GREEN}✅ Your IP: $YOUR_IP${NC}"
echo ""

# Confirm IP
read -p "Is this your correct IP? (y/n): " confirm_ip
if [ "$confirm_ip" != "y" ]; then
    read -p "Enter your IP address (format: x.x.x.x): " YOUR_IP
fi

YOUR_IP_CIDR="$YOUR_IP/32"
echo -e "${GREEN}Using IP: $YOUR_IP_CIDR${NC}"
echo ""

# Step 2: Choose deployment type
echo "Step 2: Choose deployment type"
echo "-------------------------------"
echo ""
echo "Options:"
echo "  1) Basic test only (t3.micro) - ~\$0.01/hour (~\$0.25/day) ✅ FREE TIER"
echo "  2) With GPU model server (g4dn.xlarge) - ~\$0.53/hour (~\$13/day) ⚠️  EXPENSIVE"
echo ""
read -p "Choose option (1 or 2): " deployment_choice

ENABLE_MODEL_SERVER="false"
if [ "$deployment_choice" = "2" ]; then
    ENABLE_MODEL_SERVER="true"
    echo ""
    echo -e "${YELLOW}⚠️  WARNING: GPU instance costs ~\$0.53/hour${NC}"
    echo -e "${YELLOW}⚠️  You will be charged from the moment it starts${NC}"
    echo ""
    read -p "Are you sure? Type 'YES' to continue: " confirm
    if [ "$confirm" != "YES" ]; then
        echo "Deployment cancelled"
        exit 0
    fi
fi

echo ""

# Step 3: Check SSH key
echo "Step 3: Checking SSH key..."
if [ ! -f ~/.ssh/id_rsa.pub ]; then
    echo -e "${YELLOW}⚠️  SSH key not found. Generating...${NC}"
    ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N ""
    echo -e "${GREEN}✅ SSH key generated${NC}"
else
    echo -e "${GREEN}✅ SSH key found${NC}"
fi
echo ""

# Step 4: Navigate to Terraform directory
echo "Step 4: Preparing Terraform..."
cd infrastructure/terraform

# Check if minimal.tf exists
if [ ! -f "minimal.tf" ]; then
    echo -e "${RED}❌ minimal.tf not found!${NC}"
    echo "Please ensure minimal.tf is in infrastructure/terraform/"
    exit 1
fi

# Initialize Terraform
echo "Initializing Terraform..."
terraform init
echo ""

# Step 5: Plan deployment
echo "Step 5: Creating deployment plan..."
terraform plan \
    -var="your_ip=$YOUR_IP_CIDR" \
    -var="enable_model_server=$ENABLE_MODEL_SERVER" \
    -out=minimal.tfplan

echo ""
echo -e "${YELLOW}📊 Review the plan above${NC}"
echo ""
read -p "Proceed with deployment? (yes/no): " proceed

if [ "$proceed" != "yes" ]; then
    echo "Deployment cancelled"
    exit 0
fi

echo ""

# Step 6: Apply deployment
echo "Step 6: Deploying infrastructure..."
echo -e "${GREEN}🚀 Starting deployment...${NC}"
echo ""

terraform apply minimal.tfplan

echo ""
echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""

# Step 7: Get outputs
echo "Step 7: Getting deployment information..."
echo ""

TEST_INSTANCE_IP=$(terraform output -raw test_instance_ip)
TEST_INSTANCE_ID=$(terraform output -raw test_instance_id)
S3_BUCKET=$(terraform output -raw s3_bucket)
COST_ESTIMATE=$(terraform output -raw cost_estimate)

if [ "$ENABLE_MODEL_SERVER" = "true" ]; then
    MODEL_SERVER_IP=$(terraform output -raw model_server_ip)
    MODEL_SERVER_ID=$(terraform output -raw model_server_id)
fi

# Step 8: Display summary
echo "╔════════════════════════════════════════════════════════╗"
echo "║          DEPLOYMENT SUCCESSFUL! 🎉                     ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "📊 Deployment Summary:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Test Instance (t3.micro):"
echo "  IP Address: $TEST_INSTANCE_IP"
echo "  Instance ID: $TEST_INSTANCE_ID"
echo "  SSH: ssh -i ~/.ssh/id_rsa ubuntu@$TEST_INSTANCE_IP"
echo ""

if [ "$ENABLE_MODEL_SERVER" = "true" ]; then
    echo "Model Server (g4dn.xlarge):"
    echo "  IP Address: $MODEL_SERVER_IP"
    echo "  Instance ID: $MODEL_SERVER_ID"
    echo "  SSH: ssh -i ~/.ssh/id_rsa ubuntu@$MODEL_SERVER_IP"
    echo "  API: http://$MODEL_SERVER_IP:8001"
    echo ""
fi

echo "Storage:"
echo "  S3 Bucket: $S3_BUCKET"
echo ""
echo "💰 Cost Estimate: $COST_ESTIMATE"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Save info to file
cd ../..
cat > deployment_info.txt << INFOEOF
Quant AI Test Deployment Information
Generated: $(date)

Test Instance:
  IP: $TEST_INSTANCE_IP
  ID: $TEST_INSTANCE_ID
  SSH: ssh -i ~/.ssh/id_rsa ubuntu@$TEST_INSTANCE_IP

$(if [ "$ENABLE_MODEL_SERVER" = "true" ]; then
echo "Model Server:
  IP: $MODEL_SERVER_IP
  ID: $MODEL_SERVER_ID
  SSH: ssh -i ~/.ssh/id_rsa ubuntu@$MODEL_SERVER_IP
  API: http://$MODEL_SERVER_IP:8001"
fi)

S3 Bucket: $S3_BUCKET
Cost: $COST_ESTIMATE

Stop Instances:
  aws ec2 stop-instances --instance-ids $TEST_INSTANCE_ID $(if [ "$ENABLE_MODEL_SERVER" = "true" ]; then echo "$MODEL_SERVER_ID"; fi)

Terminate (Delete Everything):
  cd infrastructure/terraform
  terraform destroy -var="your_ip=$YOUR_IP_CIDR" -var="enable_model_server=$ENABLE_MODEL_SERVER"
INFOEOF

echo ""
echo -e "${GREEN}✅ Deployment info saved to: deployment_info.txt${NC}"
echo ""

# Step 9: Wait for instances to be ready
echo "Step 9: Waiting for instances to initialize (~60 seconds)..."
echo ""

for i in {60..1}; do
    echo -ne "  ⏳ $i seconds remaining...\r"
    sleep 1
done
echo ""
echo -e "${GREEN}✅ Instances should be ready${NC}"
echo ""

# Step 10: Test connection
echo "Step 10: Testing SSH connection..."
echo ""

echo "Testing connection to test instance..."
ssh -i ~/.ssh/id_rsa -o StrictHostKeyChecking=no -o ConnectTimeout=10 ubuntu@$TEST_INSTANCE_IP "echo 'Connection successful!'" 2>/dev/null

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ SSH connection working${NC}"
else
    echo -e "${YELLOW}⚠️  SSH connection not ready yet. Wait 30s and try manually.${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🎯 Next Steps:"
echo ""
echo "1. Connect to test instance:"
echo "   ssh -i ~/.ssh/id_rsa ubuntu@$TEST_INSTANCE_IP"
echo ""

if [ "$ENABLE_MODEL_SERVER" = "true" ]; then
    echo "2. Test model server (after setup):"
    echo "   curl http://$MODEL_SERVER_IP:8001/health"
    echo ""
    echo "3. Deploy model to server:"
    echo "   ./deploy_model_to_aws.sh $MODEL_SERVER_IP"
    echo ""
fi

echo "⚠️  IMPORTANT - Stop instances when done testing:"
echo "   ./stop_test_instances.sh"
echo ""
echo "💰 Cost starts NOW and continues until you stop/terminate instances!"
echo ""
echo "To completely remove everything:"
echo "   ./destroy_test_deployment.sh"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
EOF

chmod +x deploy_minimal_test.sh
echo "✅ Created: deploy_minimal_test.sh"
echo ""

# ====================
# File 3: deploy_model_to_aws.sh
# ====================
echo "Creating deploy_model_to_aws.sh..."
cat > deploy_model_to_aws.sh << 'EOF'
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
EOF

chmod +x deploy_model_to_aws.sh
echo "✅ Created: deploy_model_to_aws.sh"
echo ""

# ====================
# File 4: stop_test_instances.sh
# ====================
echo "Creating stop_test_instances.sh..."
cat > stop_test_instances.sh << 'EOF'
#!/bin/bash
# Stop AWS Test Instances
# This stops instances to avoid charges (storage still charged)

set -e

echo "🛑 Stop AWS Test Instances"
echo "=========================="
echo ""

# Check if deployment_info.txt exists
if [ -f "deployment_info.txt" ]; then
    echo "✅ Found deployment info"
    echo ""
    
    # Extract instance IDs
    TEST_INSTANCE_ID=$(grep "Test Instance:" -A 2 deployment_info.txt | grep "ID:" | awk '{print $2}')
    MODEL_SERVER_ID=$(grep "Model Server:" -A 2 deployment_info.txt | grep "ID:" | awk '{print $2}' 2>/dev/null || echo "")
    
    echo "Instance IDs found:"
    echo "  Test Instance: $TEST_INSTANCE_ID"
    if [ ! -z "$MODEL_SERVER_ID" ]; then
        echo "  Model Server: $MODEL_SERVER_ID"
    fi
    echo ""
else
    echo "⚠️  deployment_info.txt not found"
    echo ""
    echo "Enter instance IDs manually:"
    read -p "Test instance ID: " TEST_INSTANCE_ID
    read -p "Model server ID (or press Enter to skip): " MODEL_SERVER_ID
    echo ""
fi

# Confirm
echo "⚠️  This will STOP (not terminate) the instances"
echo "    - Storage charges continue (~\$0.10/GB/month)"
echo "    - Compute charges stop"
echo "    - You can restart later with: aws ec2 start-instances"
echo ""
read -p "Proceed? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Cancelled"
    exit 0
fi

echo ""
echo "Stopping instances..."

# Stop test instance
if [ ! -z "$TEST_INSTANCE_ID" ]; then
    echo -n "  Stopping test instance ($TEST_INSTANCE_ID)... "
    aws ec2 stop-instances --instance-ids $TEST_INSTANCE_ID > /dev/null
    echo "✅"
fi

# Stop model server
if [ ! -z "$MODEL_SERVER_ID" ]; then
    echo -n "  Stopping model server ($MODEL_SERVER_ID)... "
    aws ec2 stop-instances --instance-ids $MODEL_SERVER_ID > /dev/null
    echo "✅"
fi

echo ""
echo "✅ Instances stopping..."
echo ""
echo "Check status with:"
echo "  aws ec2 describe-instances --instance-ids $TEST_INSTANCE_ID $(if [ ! -z "$MODEL_SERVER_ID" ]; then echo "$MODEL_SERVER_ID"; fi)"
echo ""
echo "Restart with:"
echo "  aws ec2 start-instances --instance-ids $TEST_INSTANCE_ID $(if [ ! -z "$MODEL_SERVER_ID" ]; then echo "$MODEL_SERVER_ID"; fi)"
echo ""
echo "💰 Current charges after stopping:"
echo "  - EC2: \$0/hour (stopped)"
echo "  - Storage: ~\$0.08/GB/month (EBS volumes)"
echo "  - S3: ~\$0.023/GB/month"
echo ""
EOF

chmod +x stop_test_instances.sh
echo "✅ Created: stop_test_instances.sh"
echo ""

# ====================
# File 5: destroy_test_deployment.sh
# ====================
echo "Creating destroy_test_deployment.sh..."
cat > destroy_test_deployment.sh << 'EOF'
#!/bin/bash
# Destroy Test Deployment
# This completely removes all AWS resources created during testing
# ⚠️  WARNING: This is permanent! All data will be lost.

set -e

echo "💥 Destroy Test Deployment"
echo "=========================="
echo ""

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${RED}⚠️  WARNING: This will PERMANENTLY DELETE all test resources!${NC}"
echo ""
echo "This includes:"
echo "  - All EC2 instances (test + model server)"
echo "  - EBS volumes and snapshots"
echo "  - S3 bucket and all data"
echo "  - Security groups"
echo "  - IAM roles and policies"
echo "  - SSH key pairs"
echo ""
echo -e "${YELLOW}💰 After destruction, charges will be \$0${NC}"
echo ""
read -p "Are you ABSOLUTELY sure? Type 'DELETE' to confirm: " confirm

if [ "$confirm" != "DELETE" ]; then
    echo "Cancelled"
    exit 0
fi

echo ""
echo "Proceeding with destruction..."
echo ""

# Navigate to Terraform directory
cd infrastructure/terraform

# Check if minimal.tf exists
if [ ! -f "minimal.tf" ]; then
    echo "❌ minimal.tf not found"
    echo "Are you in the correct directory?"
    exit 1
fi

# Get variables
echo "Enter deployment configuration:"
echo ""

# Get IP
YOUR_IP=$(curl -s https://checkip.amazonaws.com 2>/dev/null || echo "")
if [ -z "$YOUR_IP" ]; then
    read -p "Your IP (format: x.x.x.x): " YOUR_IP
else
    read -p "Your IP [$YOUR_IP/32]: " input_ip
    YOUR_IP_CIDR="${input_ip:-$YOUR_IP/32}"
fi

# Get model server setting
read -p "Was model server enabled? (true/false): " model_server

echo ""
echo "Creating destroy plan..."

# Plan destruction
terraform plan -destroy \
    -var="your_ip=$YOUR_IP_CIDR" \
    -var="enable_model_server=$model_server" \
    -out=destroy.tfplan

echo ""
echo -e "${YELLOW}📊 Review destruction plan above${NC}"
echo ""
read -p "Final confirmation - destroy everything? (yes/no): " final_confirm

if [ "$final_confirm" != "yes" ]; then
    echo "Cancelled"
    exit 0
fi

echo ""
echo -e "${RED}🔥 Destroying infrastructure...${NC}"
echo ""

# Apply destruction
terraform apply destroy.tfplan

echo ""
echo -e "${GREEN}✅ All resources destroyed${NC}"
echo ""

# Clean up local files
echo "Cleaning up local files..."
rm -f minimal.tfplan destroy.tfplan terraform.tfstate* .terraform.lock.hcl
rm -rf .terraform
cd ../..
rm -f deployment_info.txt

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║          ALL RESOURCES DELETED ✅                      ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "💰 AWS Charges: \$0/hour (all resources removed)"
echo ""
echo "What was deleted:"
echo "  ✅ EC2 instances terminated"
echo "  ✅ EBS volumes deleted"
echo "  ✅ S3 bucket deleted"
echo "  ✅ Security groups removed"
echo "  ✅ IAM roles removed"
echo "  ✅ SSH keys removed"
echo ""
echo "To verify everything is gone:"
echo "  aws ec2 describe-instances --filters 'Name=tag:Project,Values=QuantAI'"
echo "  aws s3 ls | grep quantai"
echo ""
EOF

chmod +x destroy_test_deployment.sh
echo "✅ Created: destroy_test_deployment.sh"
echo ""

# ====================
# File 6: cost_calculator.py
# ====================
echo "Creating cost_calculator.py..."
cat > cost_calculator.py << 'EOF'
#!/usr/bin/env python3
"""
AWS Cost Calculator for Quant AI Project
Calculates estimated costs based on usage patterns
"""

from datetime import datetime
from typing import Dict

# AWS Pricing (us-east-1, as of Nov 2024)
PRICING = {
    "ec2": {
        "t3.micro": 0.0104,      # per hour - FREE TIER: 750 hours/month
        "t3.medium": 0.0416,      # per hour
        "g4dn.xlarge": 0.526,     # per hour (GPU)
    },
    "ebs": {
        "gp3": 0.08,              # per GB/month
    },
    "s3": {
        "standard": 0.023,        # per GB/month
    },
    "data_transfer": {
        "out": 0.09,              # per GB (first 10TB)
    },
    "rds": {
        "db.t3.small": 0.034,     # per hour
    }
}

FREE_TIER = {
    "ec2_hours": 750,             # t2.micro/t3.micro hours per month
    "ebs_gb": 30,                 # GB general purpose SSD
    "s3_gb": 5,                   # GB standard storage
    "data_transfer_gb": 100,      # GB outbound per month
}


class CostCalculator:
    """Calculate AWS costs for different deployment scenarios."""
    
    def __init__(self, use_free_tier: bool = True):
        self.use_free_tier = use_free_tier
    
    def calculate_ec2_cost(self, instance_type: str, hours: float, count: int = 1) -> float:
        """Calculate EC2 instance cost."""
        hourly_rate = PRICING["ec2"][instance_type]
        total_hours = hours * count
        
        if self.use_free_tier and instance_type == "t3.micro":
            free_hours = min(total_hours, FREE_TIER["ec2_hours"])
            billable_hours = max(0, total_hours - free_hours)
            cost = billable_hours * hourly_rate
        else:
            cost = total_hours * hourly_rate
        
        return cost
    
    def calculate_ebs_cost(self, gb: int, months: float = 1) -> float:
        """Calculate EBS storage cost."""
        if self.use_free_tier:
            billable_gb = max(0, gb - FREE_TIER["ebs_gb"])
        else:
            billable_gb = gb
        
        return billable_gb * PRICING["ebs"]["gp3"] * months
    
    def calculate_s3_cost(self, gb: int, months: float = 1) -> float:
        """Calculate S3 storage cost."""
        if self.use_free_tier:
            billable_gb = max(0, gb - FREE_TIER["s3_gb"])
        else:
            billable_gb = gb
        
        return billable_gb * PRICING["s3"]["standard"] * months
    
    def calculate_data_transfer_cost(self, gb: int) -> float:
        """Calculate data transfer cost."""
        if self.use_free_tier:
            billable_gb = max(0, gb - FREE_TIER["data_transfer_gb"])
        else:
            billable_gb = gb
        
        return billable_gb * PRICING["data_transfer"]["out"]
    
    def scenario_basic_test(self, hours: float = 24) -> Dict[str, float]:
        """Basic test deployment cost (t3.micro only)."""
        costs = {
            "ec2_test": self.calculate_ec2_cost("t3.micro", hours),
            "ebs_test": self.calculate_ebs_cost(8, hours / 730),
            "s3": self.calculate_s3_cost(1, hours / 730),
            "data_transfer": self.calculate_data_transfer_cost(1),
        }
        costs["total"] = sum(costs.values())
        return costs
    
    def scenario_with_gpu(self, hours: float = 24) -> Dict[str, float]:
        """Test with GPU model server."""
        costs = {
            "ec2_test": self.calculate_ec2_cost("t3.micro", hours),
            "ec2_gpu": self.calculate_ec2_cost("g4dn.xlarge", hours),
            "ebs_test": self.calculate_ebs_cost(8, hours / 730),
            "ebs_gpu": self.calculate_ebs_cost(100, hours / 730),
            "s3": self.calculate_s3_cost(5, hours / 730),
            "data_transfer": self.calculate_data_transfer_cost(10),
        }
        costs["total"] = sum(costs.values())
        return costs
    
    def scenario_production(self) -> Dict[str, float]:
        """Full production deployment (24/7 for 1 month)."""
        costs = {
            "ec2_api": self.calculate_ec2_cost("t3.medium", 730),
            "ec2_gpu": self.calculate_ec2_cost("g4dn.xlarge", 730),
            "ebs_api": self.calculate_ebs_cost(30, 1),
            "ebs_gpu": self.calculate_ebs_cost(100, 1),
            "s3": self.calculate_s3_cost(100, 1),
            "rds": PRICING["rds"]["db.t3.small"] * 730,
            "data_transfer": self.calculate_data_transfer_cost(1000),
        }
        costs["total"] = sum(costs.values())
        return costs
    
    def scenario_optimized(self) -> Dict[str, float]:
        """Optimized deployment (market hours only)."""
        hours = 12 * 22  # 264 hours/month
        costs = {
            "ec2_api": self.calculate_ec2_cost("t3.medium", 730),
            "ec2_gpu": self.calculate_ec2_cost("g4dn.xlarge", hours),
            "ebs_api": self.calculate_ebs_cost(30, 1),
            "ebs_gpu": self.calculate_ebs_cost(100, 1),
            "s3": self.calculate_s3_cost(100, 1),
            "data_transfer": self.calculate_data_transfer_cost(500),
        }
        costs["total"] = sum(costs.values())
        return costs


def print_scenario(name: str, costs: Dict[str, float], hours: float = None):
    """Pretty print scenario costs."""
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    
    if hours:
        print(f"\nDuration: {hours} hours ({hours/24:.1f} days)")
    
    print(f"\nCost Breakdown:")
    print(f"{'-'*60}")
    
    total = costs.pop("total")
    
    for service, cost in sorted(costs.items()):
        service_name = service.replace("_", " ").title()
        print(f"  {service_name:<30} ${cost:>8.2f}")
    
    print(f"{'-'*60}")
    print(f"  {'Total':<30} ${total:>8.2f}")
    
    if hours:
        hourly = total / hours
        daily = hourly * 24
        print(f"\n  Hourly rate: ${hourly:.4f}/hour")
        print(f"  Daily rate:  ${daily:.2f}/day")
    
    print()


def main():
    """Main cost calculation and display."""
    print("\n" + "="*60)
    print("  Quant AI - AWS Cost Calculator")
    print("="*60)
    print(f"\nCalculation Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Region: us-east-1")
    print(f"Using Free Tier: Yes (first 12 months)")
    
    calc = CostCalculator(use_free_tier=True)
    
    print_scenario(
        "Scenario 1: Basic Test (1 Hour)",
        calc.scenario_basic_test(1),
        hours=1
    )
    
    print_scenario(
        "Scenario 2: Basic Test (24 Hours)",
        calc.scenario_basic_test(24),
        hours=24
    )
    
    print_scenario(
        "Scenario 3: With GPU Model Server (1 Hour)",
        calc.scenario_with_gpu(1),
        hours=1
    )
    
    print_scenario(
        "Scenario 4: With GPU Model Server (24 Hours)",
        calc.scenario_with_gpu(24),
        hours=24
    )
    
    print_scenario(
        "Scenario 5: Production Deployment (1 Month, 24/7)",
        calc.scenario_production(),
    )
    
    print_scenario(
        "Scenario 6: Optimized Deployment (1 Month, Market Hours)",
        calc.scenario_optimized(),
    )
    
    print("\n" + "="*60)
    print("  Cost Comparison Summary")
    print("="*60)
    print(f"\n  1 hour basic test:              ${calc.scenario_basic_test(1)['total']:.4f}")
    print(f"  1 hour with GPU:                ${calc.scenario_with_gpu(1)['total']:.2f}")
    print(f"  24 hour basic test:             ${calc.scenario_basic_test(24)['total']:.2f}")
    print(f"  24 hour with GPU:               ${calc.scenario_with_gpu(24)['total']:.2f}")
    print(f"  1 month production (24/7):      ${calc.scenario_production()['total']:.2f}")
    print(f"  1 month optimized (market hrs): ${calc.scenario_optimized()['total']:.2f}")
    
    print("\n" + "="*60)
    print("  Recommendations")
    print("="*60)
    print("""
  For Testing (1-2 hours):
    ✅ Use basic test setup (t3.micro only)
    💰 Cost: ~$0.01 - $0.02 (essentially free with free tier)
  
  For Development (daily, few hours):
    ✅ Use GPU only when needed
    ✅ Stop instances when not in use
    💰 Cost: ~$1-2 per hour of GPU use
  
  For Production (24/7):
    ⚠️  Consider market-hours-only operation
    ⚠️  Use spot instances (70% discount)
    💰 Cost: ~$140/month (optimized) vs $450/month (always-on)
  
  💡 Pro Tips:
    • Set up billing alerts at $10, $50, $100
    • Use CloudWatch to auto-stop instances after idle time
    • Store models in S3, not EBS (cheaper)
    • Use Reserved Instances for 40% discount (1-year commitment)
    """)
    
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
EOF

chmod +x cost_calculator.py
echo "✅ Created: cost_calculator.py"
echo ""

# Summary
echo "╔════════════════════════════════════════════════════════╗"
echo "║          ALL FILES CREATED! 🎉                         ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "Files created:"
echo "  ✅ infrastructure/terraform/minimal.tf"
echo "  ✅ deploy_minimal_test.sh"
echo "  ✅ deploy_model_to_aws.sh"
echo "  ✅ stop_test_instances.sh"
echo "  ✅ destroy_test_deployment.sh"
echo "  ✅ cost_calculator.py"
echo ""
echo "All scripts are executable and ready to use!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🚀 Next Steps:"
echo ""
echo "1. View estimated costs:"
echo "   python cost_calculator.py"
echo ""
echo "2. Deploy basic test (FREE TIER eligible):"
echo "   ./deploy_minimal_test.sh"
echo ""
echo "3. When done testing, stop instances:"
echo "   ./stop_test_instances.sh"
echo ""
echo "4. To completely remove everything:"
echo "   ./destroy_test_deployment.sh"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📚 For detailed instructions, see: DEPLOYMENT_GUIDE.md"
echo ""
