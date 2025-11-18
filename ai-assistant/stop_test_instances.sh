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
