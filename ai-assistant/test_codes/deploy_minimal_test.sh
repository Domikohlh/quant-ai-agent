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
