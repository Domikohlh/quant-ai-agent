#!/bin/bash
# Test Python Code on EC2
# This script helps you test Python code on your EC2 instance

set -e

if [ ! -f "deployment_info.txt" ]; then
    echo "❌ deployment_info.txt not found"
    exit 1
fi

INSTANCE_IP=$(grep "Test Instance:" -A 2 deployment_info.txt | grep "IP:" | awk '{print $2}')

echo "🐍 Python Testing on EC2"
echo "========================"
echo ""
echo "Instance IP: $INSTANCE_IP"
echo ""

# Menu
echo "Choose how to test Python code:"
echo ""
echo "  1) Run 'Hello World' test"
echo "  2) Check Python version and packages"
echo "  3) Upload and run a Python file"
echo "  4) Create and run Python script on server"
echo "  5) Interactive Python shell (remote)"
echo "  6) Test backend code from local project"
echo ""
read -p "Choose option (1-6): " choice

case $choice in
    1)
        echo ""
        echo "Running Hello World test..."
        echo ""
        ssh -i ~/.ssh/id_rsa ubuntu@$INSTANCE_IP << 'EOF'
echo "=== Python Hello World Test ==="
echo ""

# Test Python 3
echo "Testing Python 3:"
python3 -c "print('Hello World from EC2!')"
echo "✅ Python 3 works"
echo ""

# Test with a simple script
cat > /tmp/test_hello.py << 'PYEOF'
#!/usr/bin/env python3
"""
Simple Hello World test
"""

def main():
    print("=" * 50)
    print("Hello World from EC2 Instance!")
    print("=" * 50)
    print("")
    print("System information:")
    
    import sys
    import platform
    
    print(f"  Python version: {sys.version}")
    print(f"  Platform: {platform.platform()}")
    print(f"  Processor: {platform.processor()}")
    print("")
    
    # Test basic math
    result = 2 + 2
    print(f"  Math test: 2 + 2 = {result}")
    
    # Test list operations
    numbers = [1, 2, 3, 4, 5]
    total = sum(numbers)
    print(f"  Sum of {numbers} = {total}")
    
    print("")
    print("✅ All tests passed!")

if __name__ == "__main__":
    main()
PYEOF

chmod +x /tmp/test_hello.py
python3 /tmp/test_hello.py
EOF
        ;;
        
    2)
        echo ""
        echo "Checking Python environment..."
        echo ""
        ssh -i ~/.ssh/id_rsa ubuntu@$INSTANCE_IP << 'EOF'
echo "=== Python Environment ==="
echo ""

echo "Python 3 version:"
python3 --version
echo ""

echo "Python 3 location:"
which python3
echo ""

echo "Installed packages:"
pip3 list | head -20
echo "... (showing first 20 packages)"
echo ""

echo "Available Python versions:"
ls -la /usr/bin/python* 2>/dev/null || echo "None found"
echo ""

echo "Disk space:"
df -h | grep -E "Filesystem|/$"
echo ""
EOF
        ;;
        
    3)
        echo ""
        echo "Upload and run Python file"
        echo ""
        read -p "Enter path to your Python file: " py_file
        
        if [ ! -f "$py_file" ]; then
            echo "❌ File not found: $py_file"
            exit 1
        fi
        
        filename=$(basename "$py_file")
        
        echo "Uploading $filename to EC2..."
        scp -i ~/.ssh/id_rsa "$py_file" ubuntu@$INSTANCE_IP:/tmp/$filename
        
        echo "Running $filename..."
        echo ""
        ssh -i ~/.ssh/id_rsa ubuntu@$INSTANCE_IP "python3 /tmp/$filename"
        ;;
        
    4)
        echo ""
        echo "Create and run Python script on server"
        echo ""
        echo "Enter your Python code (type 'END' on a new line when done):"
        echo ""
        
        # Collect Python code
        python_code=""
        while IFS= read -r line; do
            if [ "$line" = "END" ]; then
                break
            fi
            python_code="$python_code$line"$'\n'
        done
        
        echo ""
        echo "Creating script on server..."
        
        ssh -i ~/.ssh/id_rsa ubuntu@$INSTANCE_IP "cat > /tmp/user_script.py" << EOF
$python_code
EOF
        
        echo "Running script..."
        echo ""
        ssh -i ~/.ssh/id_rsa ubuntu@$INSTANCE_IP "python3 /tmp/user_script.py"
        ;;
        
    5)
        echo ""
        echo "Opening remote Python shell..."
        echo "Type 'exit()' to quit"
        echo ""
        ssh -i ~/.ssh/id_rsa -t ubuntu@$INSTANCE_IP "python3"
        ;;
        
    6)
        echo ""
        echo "Test backend code from local project"
        echo ""
        
        if [ ! -d "backend" ]; then
            echo "❌ backend/ directory not found"
            echo "Run this from the ai-assistant directory"
            exit 1
        fi
        
        echo "Uploading backend code..."
        ssh -i ~/.ssh/id_rsa ubuntu@$INSTANCE_IP "mkdir -p ~/quantai_test"
        scp -i ~/.ssh/id_rsa -r backend ubuntu@$INSTANCE_IP:~/quantai_test/
        
        echo "Creating test environment on server..."
        ssh -i ~/.ssh/id_rsa ubuntu@$INSTANCE_IP << 'EOF'
cd ~/quantai_test

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install basic dependencies
pip install --upgrade pip
pip install pydantic python-dotenv structlog

echo ""
echo "✅ Environment ready"
echo ""
echo "Testing backend imports..."

python3 << 'PYEOF'
import sys
sys.path.insert(0, '/home/ubuntu/quantai_test')

try:
    from backend.core.config.settings import settings
    print("✅ Can import settings")
    print(f"   App name: {settings.app_name}")
    print(f"   Environment: {settings.environment}")
except Exception as e:
    print(f"⚠️  Import error: {e}")

print("")
print("Backend code is accessible on EC2!")
PYEOF
EOF
        ;;
        
    *)
        echo "❌ Invalid option"
        exit 1
        ;;
esac

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📝 More Python testing commands:"
echo ""
echo "Run Python command remotely:"
echo "  ssh -i ~/.ssh/id_rsa ubuntu@$INSTANCE_IP 'python3 -c \"print(2+2)\"'"
echo ""
echo "Copy file to EC2:"
echo "  scp -i ~/.ssh/id_rsa myfile.py ubuntu@$INSTANCE_IP:/tmp/"
echo ""
echo "Run uploaded file:"
echo "  ssh -i ~/.ssh/id_rsa ubuntu@$INSTANCE_IP 'python3 /tmp/myfile.py'"
echo ""
echo "Interactive SSH with Python:"
echo "  ssh -i ~/.ssh/id_rsa ubuntu@$INSTANCE_IP"
echo "  python3"
echo ""
