#!/bin/bash
# Model Server Initialization Script
# This runs on first boot of the GPU EC2 instance

set -e

# Logging
exec > >(tee -a /var/log/model_server_init.log)
exec 2>&1

echo "=========================================="
echo "Model Server Initialization Started"
echo "Time: $(date)"
echo "=========================================="

# Update system
echo "Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq

# Install essential packages
echo "Installing essential packages..."
apt-get install -y \
    build-essential \
    curl \
    git \
    htop \
    nvtop \
    tmux \
    vim \
    wget \
    python3-pip \
    python3-venv

# Check NVIDIA drivers (should be pre-installed on Deep Learning AMI)
echo "Checking NVIDIA drivers..."
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi
    echo "✅ NVIDIA drivers detected"
else
    echo "⚠️  No NVIDIA drivers found"
    echo "Installing NVIDIA drivers..."
    apt-get install -y nvidia-driver-525 nvidia-dkms-525
fi

# Install Docker
echo "Installing Docker..."
apt-get install -y \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release

curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -qq
apt-get install -y docker-ce docker-ce-cli containerd.io

# Install NVIDIA Container Toolkit
echo "Installing NVIDIA Container Toolkit..."
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
    tee /etc/apt/sources.list.d/nvidia-docker.list

apt-get update -qq
apt-get install -y nvidia-container-toolkit

systemctl restart docker
systemctl enable docker
usermod -aG docker ubuntu

# Create directories
echo "Creating working directories..."
mkdir -p /home/ubuntu/quantai-production/{models,logs}
chown -R ubuntu:ubuntu /home/ubuntu/quantai-production

# Install Python 3.11
echo "Setting up Python..."
if ! command -v python3.11 &> /dev/null; then
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -qq
    apt-get install -y python3.11 python3.11-venv python3.11-dev
fi

# Create virtual environment
echo "Creating Python virtual environment..."
su - ubuntu -c "cd /home/ubuntu/quantai-production && python3.11 -m venv venv"

# Install PyTorch
echo "Installing PyTorch..."
su - ubuntu -c "
    source /home/ubuntu/quantai-production/venv/bin/activate
    pip install --upgrade pip setuptools wheel
    pip install torch==2.1.2 --index-url https://download.pytorch.org/whl/cu121
"

# Create README
cat > /home/ubuntu/README.txt << 'EOF'
Quant AI Model Server - GPU Instance

Working Directory: ~/quantai-production
GPU Check: nvidia-smi
Monitor GPU: watch -n 2 nvidia-smi

Next: Deploy model with deploy_production_model.sh
EOF
chown ubuntu:ubuntu /home/ubuntu/README.txt

# Create marker
touch /home/ubuntu/model-server-initialized
chown ubuntu:ubuntu /home/ubuntu/model-server-initialized

echo "✅ Model Server Initialization Complete"
echo "Rebooting..."
sleep 5
reboot
