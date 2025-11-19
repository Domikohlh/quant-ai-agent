#!/bin/bash
# API Server Initialization Script
# This runs on first boot of the API EC2 instance

set -e

# Logging
exec > >(tee -a /var/log/api_server_init.log)
exec 2>&1

echo "=========================================="
echo "API Server Initialization Started"
echo "Time: $(date)"
echo "=========================================="

# Update system
echo "Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq

# Install packages
echo "Installing essential packages..."
apt-get install -y \
    build-essential \
    curl \
    git \
    htop \
    tmux \
    vim \
    wget \
    python3-pip \
    python3-venv \
    postgresql-client \
    libpq-dev \
    nginx \
    redis-server

# Install Docker
echo "Installing Docker..."
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
usermod -aG docker ubuntu

# Install Python 3.11
echo "Setting up Python 3.11..."
if ! command -v python3.11 &> /dev/null; then
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -qq
    apt-get install -y python3.11 python3.11-venv python3.11-dev
fi

# Create directories
echo "Creating working directories..."
mkdir -p /home/ubuntu/quantai-api/{backend,logs,data}
chown -R ubuntu:ubuntu /home/ubuntu/quantai-api

# Create virtual environment
echo "Creating Python virtual environment..."
su - ubuntu -c "cd /home/ubuntu/quantai-api && python3.11 -m venv venv"

# Install basic packages
echo "Installing Python packages..."
su - ubuntu -c "
    source /home/ubuntu/quantai-api/venv/bin/activate
    pip install --upgrade pip setuptools wheel
    pip install fastapi uvicorn[standard] sqlalchemy asyncpg alembic redis celery
"

# Configure Nginx
echo "Configuring Nginx..."
cat > /etc/nginx/sites-available/quantai << 'EOF'
server {
    listen 80;
    server_name _;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    location /health {
        proxy_pass http://localhost:8000/health;
        access_log off;
    }
}
EOF

ln -sf /etc/nginx/sites-available/quantai /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx
systemctl enable nginx

# Configure Redis
systemctl enable redis-server
systemctl start redis-server

# Configure firewall
ufw --force enable
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 8000/tcp

# Create README
cat > /home/ubuntu/README.txt << 'EOF'
Quant AI API Server

Working Directory: ~/quantai-api
Deploy: ./deploy.sh

Services:
  - Nginx: systemctl status nginx
  - Redis: systemctl status redis-server

Health: curl http://localhost:8000/health
EOF
chown ubuntu:ubuntu /home/ubuntu/README.txt

# Create deployment script
cat > /home/ubuntu/deploy.sh << 'EOF'
#!/bin/bash
set -e
cd ~/quantai-api
source venv/bin/activate
[ -f requirements.txt ] && pip install -r requirements.txt
[ -d backend ] && cd backend && alembic upgrade head && cd ..
echo "✅ Deployment complete"
EOF
chmod +x /home/ubuntu/deploy.sh
chown ubuntu:ubuntu /home/ubuntu/deploy.sh

# Create marker
touch /home/ubuntu/api-server-initialized
chown ubuntu:ubuntu /home/ubuntu/api-server-initialized

echo "✅ API Server Initialization Complete"
