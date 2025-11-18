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
