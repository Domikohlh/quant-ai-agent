#!/bin/bash
# Test S3 bucket creation and access
# This verifies your AWS credentials can work with S3

set -e

echo "🪣 Testing S3 Bucket Access"
echo "==========================="
echo ""

# Generate unique bucket name
TIMESTAMP=$(date +%s)
BUCKET_NAME="quantai-test-${TIMESTAMP}"

echo "Step 1: Creating test bucket..."
echo "Bucket name: $BUCKET_NAME"
echo ""

# Create bucket
aws s3api create-bucket \
    --bucket $BUCKET_NAME \
    --region us-east-1

if [ $? -eq 0 ]; then
    echo "✅ Bucket created successfully"
else
    echo "❌ Failed to create bucket"
    exit 1
fi

echo ""
echo "Step 2: Testing bucket operations..."

# Create a test file
echo "This is a test file from Quant AI" > /tmp/test.txt

# Upload file
echo "Uploading test file..."
aws s3 cp /tmp/test.txt s3://$BUCKET_NAME/test.txt

# List bucket contents
echo ""
echo "Bucket contents:"
aws s3 ls s3://$BUCKET_NAME/

# Download file
echo ""
echo "Downloading file..."
aws s3 cp s3://$BUCKET_NAME/test.txt /tmp/test-download.txt

# Verify download
if diff /tmp/test.txt /tmp/test-download.txt > /dev/null; then
    echo "✅ File upload/download successful"
else
    echo "❌ File verification failed"
fi

echo ""
echo "Step 3: Cleaning up..."

# Delete file
aws s3 rm s3://$BUCKET_NAME/test.txt

# Delete bucket
aws s3api delete-bucket --bucket $BUCKET_NAME

echo "✅ Test bucket deleted"

# Clean up local files
rm -f /tmp/test.txt /tmp/test-download.txt

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║          S3 TEST SUCCESSFUL! ✅                        ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "Your AWS credentials can:"
echo "  ✅ Create S3 buckets"
echo "  ✅ Upload files"
echo "  ✅ Download files"
echo "  ✅ Delete buckets"
echo ""
echo "You're ready to proceed with Terraform deployment!"
echo ""
