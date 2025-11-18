#!/bin/bash
# Test Terraform Configuration
# This script validates your AWS setup without deploying anything

echo "🔍 Testing Terraform Configuration"
echo "===================================="
echo ""

# Step 1: Check Terraform installation
echo "Step 1: Checking Terraform installation..."
if command -v terraform &> /dev/null; then
    echo "✅ Terraform installed: $(terraform version | head -n1)"
else
    echo "❌ Terraform not found!"
    echo ""
    echo "Install Terraform:"
    echo "  macOS: brew install terraform"
    echo "  Linux: https://developer.hashicorp.com/terraform/install"
    exit 1
fi

echo ""

# Step 2: Check AWS credentials
echo "Step 2: Verifying AWS credentials..."
python3 << 'EOF'
import boto3
try:
    sts = boto3.client('sts')
    identity = sts.get_caller_identity()
    print(f"✅ AWS User: {identity['Arn']}")
    print(f"✅ Account: {identity['Account']}")
except Exception as e:
    print(f"❌ AWS credentials error: {e}")
    exit(1)
EOF

if [ $? -ne 0 ]; then
    echo "❌ AWS credentials not configured properly"
    exit 1
fi

echo ""

# Step 3: Test AWS access for required services
echo "Step 3: Testing AWS service access..."

# Test EC2
echo -n "  Testing EC2 access... "
if aws ec2 describe-regions --region us-east-1 &> /dev/null; then
    echo "✅"
else
    echo "❌"
fi

# Test S3
echo -n "  Testing S3 access... "
if aws s3 ls &> /dev/null; then
    echo "✅"
else
    echo "❌"
fi

# Test IAM
echo -n "  Testing IAM access... "
if aws iam get-user &> /dev/null; then
    echo "✅"
else
    echo "❌"
fi

echo ""

# Step 4: Navigate to Terraform directory
echo "Step 4: Checking Terraform files..."
if [ -d "infrastructure/terraform" ]; then
    cd infrastructure/terraform
    echo "✅ Found Terraform directory"
else
    echo "❌ Terraform directory not found"
    echo "   Expected: infrastructure/terraform"
    exit 1
fi

echo ""

# Step 5: Initialize Terraform (doesn't create resources)
echo "Step 5: Initializing Terraform..."
terraform init -input=false

if [ $? -ne 0 ]; then
    echo "❌ Terraform init failed"
    exit 1
fi

echo ""

# Step 6: Validate Terraform configuration
echo "Step 6: Validating Terraform configuration..."
terraform validate

if [ $? -ne 0 ]; then
    echo "❌ Terraform validation failed"
    exit 1
fi

echo ""

# Step 7: Format check
echo "Step 7: Checking Terraform formatting..."
terraform fmt -check -recursive

echo ""

# Step 8: Create a plan (doesn't deploy)
echo "Step 8: Creating Terraform plan..."
echo "⚠️  This will show what WOULD be created, but won't create anything yet"
echo ""

# Prompt for your IP address
echo "Enter your IP address for SSH access (or press Enter to skip):"
read -p "Your IP (e.g., 203.0.113.0/32): " your_ip

if [ -z "$your_ip" ]; then
    echo "⚠️  Skipping plan creation (IP required)"
else
    terraform plan -var="your_ip=$your_ip" -out=test.tfplan
    
    if [ $? -eq 0 ]; then
        echo ""
        echo "✅ Terraform plan created successfully!"
        echo ""
        echo "📊 Review the plan above to see what would be created:"
        echo "   - VPC and networking"
        echo "   - Security groups"
        echo "   - EC2 instances (NOT created yet)"
        echo "   - S3 buckets"
        echo "   - IAM roles"
        echo ""
        echo "💰 Estimated monthly cost: ~\$450 (if deployed 24/7)"
    else
        echo "❌ Terraform plan failed"
        exit 1
    fi
fi

echo ""
echo "===================================="
echo "✅ All tests passed!"
echo ""
echo "Next steps:"
echo "  1. Review the plan output above"
echo "  2. If satisfied, proceed to minimal deployment test"
echo "  3. Run: ./deploy_minimal_test.sh"
echo ""
echo "⚠️  Note: No resources have been created yet!"
