#!/bin/bash
# Full Production Deployment Script
# Deploys complete infrastructure with GPU model server and API

set -e

echo "🚀 Quant AI - Full Production Deployment"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
TERRAFORM_DIR="infrastructure/terraform"
PROJECT_NAME="quantai"
ENVIRONMENT="production"

# Step 1: Pre-flight checks
echo "Step 1: Pre-flight Checks"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if we're in the right directory
if [ ! -d "$TERRAFORM_DIR" ]; then
    echo -e "${RED}❌ Error: infrastructure/terraform directory not found${NC}"
    echo "Please run this script from the ai-assistant directory"
    exit 1
fi

# Check AWS credentials
echo "Checking AWS credentials..."
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}❌ AWS credentials not configured${NC}"
    exit 1
fi
echo -e "${GREEN}✅ AWS credentials OK${NC}"

# Check Terraform
echo "Checking Terraform..."
if ! command -v terraform &> /dev/null; then
    echo -e "${RED}❌ Terraform not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Terraform $(terraform version | head -1)${NC}"

# Check SSH key
echo "Checking SSH key..."
if [ ! -f ~/.ssh/id_rsa.pub ]; then
    echo -e "${YELLOW}⚠️  Generating SSH key...${NC}"
    ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N ""
fi
echo -e "${GREEN}✅ SSH key exists${NC}"

# Check .env file
echo "Checking .env configuration..."
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ .env file not found${NC}"
    exit 1
fi
echo -e "${GREEN}✅ .env file exists${NC}"

echo ""

# Step 2: Cost Warning
echo "Step 2: Cost Warning"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${YELLOW}⚠️  COST WARNING ⚠️${NC}"
echo ""
echo "This deployment will create:"
echo "  - GPU Model Server (g4dn.xlarge) → ~\$385/month"
echo "  - API Server (t3.medium) → ~\$30/month"
echo "  - RDS PostgreSQL → ~\$25/month"
echo "  - Storage & Networking → ~\$100/month"
echo ""
echo -e "${RED}Total Estimated Cost: ~\$540/month (24/7)${NC}"
echo ""
echo "Cost optimization options:"
echo "  1. Run only during market hours → ~\$290/month"
echo "  2. Stop when not in use → ~\$43/month (storage only)"
echo "  3. Use spot instances → Save 70%"
echo ""
read -p "Do you understand and accept these costs? Type 'YES' to continue: " cost_confirm

if [ "$cost_confirm" != "YES" ]; then
    echo "Deployment cancelled"
    exit 0
fi

echo ""

# Step 3: Configuration
echo "Step 3: Configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Get IP address
echo "Detecting your IP address..."
YOUR_IP=$(curl -s https://checkip.amazonaws.com)
echo -e "${GREEN}Your IP: $YOUR_IP${NC}"
echo ""
read -p "Is this correct? (y/n): " ip_confirm

if [ "$ip_confirm" != "y" ]; then
    read -p "Enter your IP address: " YOUR_IP
fi

YOUR_IP_CIDR="$YOUR_IP/32"

# Model selection
echo ""
echo "Select model to deploy:"
echo "  1) Small test model (distilgpt2 ~350MB) - For testing"
echo "  2) Medium model (Llama 3.2 3B ~6GB) - Recommended"
echo "  3) Large model (Llama 3.2 7B ~14GB) - High performance"
echo "  4) Custom model path"
echo ""
read -p "Choose option (1-4): " model_choice

case $model_choice in
    1)
        MODEL_NAME="distilgpt2"
        ;;
    2)
        MODEL_NAME="meta-llama/Llama-3.2-3B-Instruct"
        ;;
    3)
        MODEL_NAME="meta-llama/Llama-3.2-7B-Instruct"
        ;;
    4)
        read -p "Enter model name/path: " MODEL_NAME
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}Configuration:${NC}"
echo "  IP Address: $YOUR_IP_CIDR"
echo "  Project: $PROJECT_NAME"
echo "  Environment: $ENVIRONMENT"
echo "  Model: $MODEL_NAME"
echo ""
read -p "Proceed with deployment? (yes/no): " proceed_confirm

if [ "$proceed_confirm" != "yes" ]; then
    echo "Deployment cancelled"
    exit 0
fi

echo ""

# Step 4: Initialize Terraform
echo "Step 4: Initialize Terraform"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd $TERRAFORM_DIR

echo "Initializing Terraform..."
terraform init -upgrade

echo "Validating configuration..."
terraform validate

echo -e "${GREEN}✅ Terraform initialized${NC}"
echo ""

# Step 5: Plan Infrastructure
echo "Step 5: Plan Infrastructure"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Creating deployment plan..."
terraform plan \
    -var="your_ip=$YOUR_IP_CIDR" \
    -var="project_name=$PROJECT_NAME" \
    -var="environment=$ENVIRONMENT" \
    -out=production.tfplan

echo ""
echo -e "${YELLOW}📊 Please review the plan above${NC}"
echo ""
read -p "Apply this plan? (yes/no): " apply_confirm

if [ "$apply_confirm" != "yes" ]; then
    echo "Deployment cancelled"
    cd ../..
    exit 0
fi

echo ""

# Step 6: Deploy Infrastructure
echo "Step 6: Deploy Infrastructure"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo -e "${GREEN}🚀 Deploying infrastructure...${NC}"
echo "This will take 5-10 minutes..."
echo ""

terraform apply production.tfplan

echo ""
echo -e "${GREEN}✅ Infrastructure deployed!${NC}"
echo ""

# Step 7: Get Deployment Info
echo "Step 7: Saving Deployment Info"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Get outputs
MODEL_SERVER_IP=$(terraform output -raw model_server_ip)
MODEL_SERVER_ID=$(terraform output -raw model_server_id)
API_SERVER_IP=$(terraform output -raw api_server_ip)
API_SERVER_ID=$(terraform output -raw api_server_id)
RDS_ENDPOINT=$(terraform output -raw rds_endpoint)
S3_BUCKET=$(terraform output -raw s3_bucket)

# Save to file
cd ../..
cat > deployment_production.txt << EOF
Quant AI Production Deployment
Generated: $(date)

Model Server (g4dn.xlarge):
  IP: $MODEL_SERVER_IP
  ID: $MODEL_SERVER_ID
  SSH: ssh -i ~/.ssh/id_rsa ubuntu@$MODEL_SERVER_IP
  API: http://$MODEL_SERVER_IP:8001
  Model: $MODEL_NAME

API Server (t3.medium):
  IP: $API_SERVER_IP
  ID: $API_SERVER_ID
  SSH: ssh -i ~/.ssh/id_rsa ubuntu@$API_SERVER_IP
  API: http://$API_SERVER_IP:8000

Database:
  Endpoint: $RDS_ENDPOINT
  Database: quantai_db
  Username: quantai

Storage:
  S3 Bucket: $S3_BUCKET

Management Commands:
  Stop instances:
    aws ec2 stop-instances --instance-ids $MODEL_SERVER_ID $API_SERVER_ID
  
  Start instances:
    aws ec2 start-instances --instance-ids $MODEL_SERVER_ID $API_SERVER_ID
  
  Destroy everything:
    cd infrastructure/terraform
    terraform destroy -var="your_ip=$YOUR_IP_CIDR"

Cost: ~\$540/month (24/7), ~\$290/month (market hours only)
EOF

echo -e "${GREEN}✅ Deployment info saved to: deployment_production.txt${NC}"
echo ""

# Step 8: Display Summary
echo "╔════════════════════════════════════════════════════════════╗"
echo "║          INFRASTRUCTURE DEPLOYED! 🎉                       ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 Deployment Summary:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Model Server (GPU):"
echo "  IP: $MODEL_SERVER_IP"
echo "  Type: g4dn.xlarge (NVIDIA T4 GPU)"
echo ""
echo "API Server:"
echo "  IP: $API_SERVER_IP"
echo "  Type: t3.medium"
echo ""
echo "Database:"
echo "  Endpoint: $RDS_ENDPOINT"
echo ""
echo "Storage:"
echo "  S3 Bucket: $S3_BUCKET"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 9: Wait for Instances
echo "Step 9: Waiting for Instances to Initialize"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Waiting 120 seconds for instances to boot..."

for i in {120..1}; do
    echo -ne "  ⏳ $i seconds remaining...\r"
    sleep 1
done
echo ""
echo -e "${GREEN}✅ Instances should be ready${NC}"
echo ""

# Step 10: Next Steps
echo "Step 10: Next Steps"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🎯 What to do next:"
echo ""
echo "1. Deploy model to GPU server:"
echo "   ./deploy_production_model.sh $MODEL_SERVER_IP $MODEL_NAME"
echo ""
echo "2. Setup API server:"
echo "   ./setup_api_server.sh $API_SERVER_IP $MODEL_SERVER_IP"
echo ""
echo "3. Test deployment:"
echo "   ./test_production.sh"
echo ""
echo "4. Monitor costs:"
echo "   aws ce get-cost-and-usage --time-period Start=\$(date +%Y-%m-01),End=\$(date +%Y-%m-%d) --granularity MONTHLY --metrics BlendedCost"
echo ""
echo "⚠️  IMPORTANT: Instances are running and costing money!"
echo ""
echo "To stop instances (save costs):"
echo "  ./stop_production.sh"
echo ""
echo "To destroy everything:"
echo "  ./destroy_production.sh"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${GREEN}✅ Production deployment complete!${NC}"
echo ""
