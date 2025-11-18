#!/bin/bash
# Fix SSH Timeout Issue
# This script diagnoses and fixes the most common cause: IP whitelist

set -e

echo "🔧 Fixing SSH Connection Timeout"
echo "================================="
echo ""

# Get instance info
if [ ! -f "deployment_info.txt" ]; then
    echo "❌ deployment_info.txt not found"
    exit 1
fi

TEST_IP=$(grep "Test Instance:" -A 2 deployment_info.txt | grep "IP:" | awk '{print $2}')
TEST_ID=$(grep "Test Instance:" -A 2 deployment_info.txt | grep "ID:" | awk '{print $2}')

echo "Instance IP: $TEST_IP"
echo "Instance ID: $TEST_ID"
echo ""

# Step 1: Check if instance is running
echo "Step 1: Checking instance status..."
INSTANCE_STATE=$(aws ec2 describe-instances \
    --instance-ids $TEST_ID \
    --query 'Reservations[0].Instances[0].State.Name' \
    --output text 2>/dev/null || echo "error")

if [ "$INSTANCE_STATE" = "error" ]; then
    echo "❌ Cannot query AWS. Check your credentials:"
    echo "   aws sts get-caller-identity"
    exit 1
fi

echo "   Instance state: $INSTANCE_STATE"

if [ "$INSTANCE_STATE" != "running" ]; then
    echo "❌ Instance is not running!"
    if [ "$INSTANCE_STATE" = "pending" ]; then
        echo "   Instance is still starting. Wait 1-2 minutes and try again."
    fi
    exit 1
fi

echo "   ✅ Instance is running"
echo ""

# Step 2: Check your current IP
echo "Step 2: Checking your IP address..."
YOUR_IP=$(curl -s https://checkip.amazonaws.com || curl -s https://api.ipify.org || curl -s https://ifconfig.me)

if [ -z "$YOUR_IP" ]; then
    echo "❌ Cannot detect your IP address"
    read -p "Enter your IP address manually: " YOUR_IP
fi

echo "   Your current IP: $YOUR_IP"
echo ""

# Step 3: Get security group
echo "Step 3: Checking security group..."
SG_ID=$(aws ec2 describe-instances \
    --instance-ids $TEST_ID \
    --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' \
    --output text)

echo "   Security Group ID: $SG_ID"
echo ""

# Step 4: Check allowed IPs
echo "Step 4: Checking allowed IPs in security group..."
ALLOWED_IPS=$(aws ec2 describe-security-groups \
    --group-ids $SG_ID \
    --query 'SecurityGroups[0].IpPermissions[?FromPort==`22`].IpRanges[].CidrIp' \
    --output text)

echo "   Currently allowed IPs:"
echo "   $ALLOWED_IPS"
echo ""

# Check if your IP is allowed
IP_ALLOWED=false
for allowed_cidr in $ALLOWED_IPS; do
    # Remove /32 from CIDR
    allowed_ip=${allowed_cidr%/*}
    if [ "$allowed_ip" = "$YOUR_IP" ]; then
        IP_ALLOWED=true
        break
    fi
done

if [ "$IP_ALLOWED" = true ]; then
    echo "   ✅ Your IP is already allowed"
else
    echo "   ⚠️  Your IP ($YOUR_IP) is NOT in the allowed list!"
    echo ""
    echo "   This is the most common cause of timeout errors."
    echo ""
    read -p "   Add your current IP to security group? (yes/no): " add_ip
    
    if [ "$add_ip" = "yes" ]; then
        echo ""
        echo "   Adding $YOUR_IP/32 to security group..."
        
        aws ec2 authorize-security-group-ingress \
            --group-id $SG_ID \
            --protocol tcp \
            --port 22 \
            --cidr $YOUR_IP/32 2>&1 | grep -v "already exists" || true
        
        echo "   ✅ IP added to security group"
        echo ""
    else
        echo ""
        echo "   Cannot proceed without adding your IP."
        echo "   Add it manually in AWS Console or run this script again."
        exit 1
    fi
fi

# Step 5: Wait for instance to be fully ready
echo "Step 5: Waiting for instance to be fully ready..."

max_wait=120  # 2 minutes
elapsed=0

while [ $elapsed -lt $max_wait ]; do
    # Check system status
    STATUS=$(aws ec2 describe-instance-status \
        --instance-ids $TEST_ID \
        --query 'InstanceStatuses[0].SystemStatus.Status' \
        --output text 2>/dev/null || echo "initializing")
    
    if [ "$STATUS" = "ok" ]; then
        echo "   ✅ Instance system checks passed"
        break
    fi
    
    echo -ne "   Status: $STATUS... waiting ($elapsed/$max_wait seconds)\r"
    sleep 5
    elapsed=$((elapsed + 5))
done

echo ""
echo ""

# Step 6: Try SSH connection
echo "Step 6: Testing SSH connection..."
echo ""

for attempt in {1..5}; do
    echo "   Attempt $attempt/5..."
    
    if timeout 10 ssh -i ~/.ssh/id_rsa \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout=8 \
        -o BatchMode=yes \
        ubuntu@$TEST_IP "echo 'Connection successful'" 2>/dev/null; then
        
        echo ""
        echo "╔════════════════════════════════════════════════════════╗"
        echo "║          SSH CONNECTION FIXED! ✅                      ║"
        echo "╚════════════════════════════════════════════════════════╝"
        echo ""
        echo "You can now connect with:"
        echo "  ssh -i ~/.ssh/id_rsa ubuntu@$TEST_IP"
        echo ""
        
        read -p "Open SSH session now? (yes/no): " open_now
        if [ "$open_now" = "yes" ]; then
            echo ""
            ssh -i ~/.ssh/id_rsa ubuntu@$TEST_IP
        fi
        
        exit 0
    fi
    
    if [ $attempt -lt 5 ]; then
        echo "   Connection failed, waiting 10 seconds..."
        sleep 10
    fi
done

# If we get here, connection still failed
echo ""
echo "❌ SSH connection still timing out after fixes"
echo ""
echo "Additional troubleshooting:"
echo ""
echo "1. Check if you're behind a VPN or firewall:"
echo "   - Try disconnecting VPN"
echo "   - Try from a different network"
echo ""
echo "2. Verify your IP hasn't changed:"
echo "   curl https://checkip.amazonaws.com"
echo ""
echo "3. Check instance console output for errors:"
echo "   aws ec2 get-console-output --instance-id $TEST_ID --output text"
echo ""
echo "4. Try connecting from AWS Console (Session Manager):"
echo "   https://console.aws.amazon.com/ec2/v2/home#Instances:instanceId=$TEST_ID"
echo ""
echo "5. Check if port 22 is reachable:"
echo "   nc -zv $TEST_IP 22"
echo ""
