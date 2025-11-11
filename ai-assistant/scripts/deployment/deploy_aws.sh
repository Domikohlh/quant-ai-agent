#!/bin/bash
# AWS Deployment Script for Quant AI
set -e

echo "🚀 Starting Quant AI AWS Deployment..."

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
else
    echo "❌ .env file not found! Please create one from .env.template"
    exit 1
fi

# Check required tools
command -v terraform >/dev/null 2>&1 || { echo "❌ Terraform not installed"; exit 1; }
command -v aws >/dev/null 2>&1 || { echo "❌ AWS CLI not installed"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "❌ Docker not installed"; exit 1; }

# Set AWS credentials
export AWS_REGION=${AWS_REGION:-us-east-1}
echo "🔑 Configuring AWS credentials..."
aws configure set aws_access_key_id $AWS_ACCESS_KEY_ID
aws configure set aws_secret_access_key $AWS_SECRET_ACCESS_KEY
aws configure set default.region $AWS_REGION

# Initialize Terraform
echo "📦 Initializing Terraform..."
cd infrastructure/terraform
terraform init

# Plan infrastructure
echo "📋 Planning infrastructure..."
terraform plan -out=tfplan

# Apply infrastructure
read -p "Apply Terraform plan? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "❌ Deployment cancelled"
    exit 1
fi

echo "🏗️  Creating AWS infrastructure..."
terraform apply tfplan

# Get outputs
MODEL_SERVER_IP=$(terraform output -raw model_server_ip)
API_SERVER_IP=$(terraform output -raw api_server_ip)
S3_BUCKET=$(terraform output -raw s3_bucket)

echo "✅ Infrastructure created:"
echo "  - Model Server: $MODEL_SERVER_IP"
echo "  - API Server: $API_SERVER_IP"
echo "  - S3 Bucket: $S3_BUCKET"

cd ../..

# Download model weights
echo "📥 Downloading model weights..."
python scripts/deployment/download_models.py

# Upload models to S3
echo "☁️  Uploading models to S3..."
aws s3 sync data/models/ s3://$S3_BUCKET/models/ --exclude "*" --include "gpt-oss-20b/*"

# Build Docker images
echo "🐳 Building Docker images..."
docker build -t quantai-api:latest -f docker/api/Dockerfile .
docker build -t quantai-model:latest -f docker/model/Dockerfile .

# Tag and push to ECR (optional)
if [ "$USE_ECR" = "true" ]; then
    echo "📤 Pushing to ECR..."
    aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REGISTRY
    docker tag quantai-api:latest $ECR_REGISTRY/quantai-api:latest
    docker tag quantai-model:latest $ECR_REGISTRY/quantai-model:latest
    docker push $ECR_REGISTRY/quantai-api:latest
    docker push $ECR_REGISTRY/quantai-model:latest
fi

# Wait for EC2 instances to be ready
echo "⏳ Waiting for EC2 instances to initialize..."
sleep 60

# Deploy to Model Server
echo "🚀 Deploying to Model Server..."
ssh -o StrictHostKeyChecking=no -i ~/.ssh/quantai-key.pem ubuntu@$MODEL_SERVER_IP << 'EOF'
    # Install Docker
    sudo apt-get update
    sudo apt-get install -y docker.io docker-compose
    sudo usermod -aG docker ubuntu
    
    # Pull model image
    docker pull quantai-model:latest
    
    # Run model server
    docker run -d \
        --name quantai-model \
        --gpus all \
        -p 8001:8001 \
        -v /models:/models \
        -e PRIMARY_MODEL_PATH=/models/gpt-oss-20b \
        -e MODEL_SERVER_API_KEY=$MODEL_SERVER_API_KEY \
        --restart unless-stopped \
        quantai-model:latest
    
    echo "✅ Model server deployed"
EOF

# Deploy to API Server
echo "🚀 Deploying to API Server..."
ssh -o StrictHostKeyChecking=no -i ~/.ssh/quantai-key.pem ubuntu@$API_SERVER_IP << 'EOF'
    # Install Docker
    sudo apt-get update
    sudo apt-get install -y docker.io docker-compose
    sudo usermod -aG docker ubuntu
    
    # Create docker-compose.yml
    cat > docker-compose.yml << 'COMPOSE_EOF'
version: '3.8'
services:
  postgres:
    image: timescale/timescaledb:latest-pg15
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped
  
  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped
  
  api:
    image: quantai-api:latest
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - MODEL_SERVER_URL=http://${MODEL_SERVER_IP}:8001
    depends_on:
      - postgres
      - redis
    restart: unless-stopped
  
  celery_worker:
    image: quantai-api:latest
    command: celery -A backend.core.celery_app worker --loglevel=info
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - CELERY_BROKER_URL=${CELERY_BROKER_URL}
    depends_on:
      - redis
      - postgres
    restart: unless-stopped
  
  celery_beat:
    image: quantai-api:latest
    command: celery -A backend.core.celery_app beat --loglevel=info
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - CELERY_BROKER_URL=${CELERY_BROKER_URL}
    depends_on:
      - redis
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
COMPOSE_EOF
    
    # Start services
    docker-compose up -d
    
    echo "✅ API server deployed"
EOF

# Update .env with server IPs
echo "📝 Updating .env file..."
sed -i.bak "s|MODEL_SERVER_URL=.*|MODEL_SERVER_URL=http://$MODEL_SERVER_IP:8001|g" .env
sed -i.bak "s|API_SERVER_URL=.*|API_SERVER_URL=http://$API_SERVER_IP:8000|g" .env

echo "✅ Deployment completed successfully!"
echo ""
echo "🔗 Access URLs:"
echo "  API Server: http://$API_SERVER_IP:8000"
echo "  API Docs: http://$API_SERVER_IP:8000/docs"
echo "  Model Server: http://$MODEL_SERVER_IP:8001"
echo ""
echo "📊 Monitor deployment:"
echo "  Flower (Celery): http://$API_SERVER_IP:5555"
echo "  Prometheus: http://$API_SERVER_IP:9090"
echo "  Grafana: http://$API_SERVER_IP:3000"
echo ""
echo "📝 Next steps:"
echo "  1. Run database migrations: ./scripts/deployment/run_migrations.sh"
echo "  2. Test API: curl http://$API_SERVER_IP:8000/health"
echo "  3. Start frontend development"
