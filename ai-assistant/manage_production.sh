#!/bin/bash
# Production Management Tool
# Centralized script for managing production deployment

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

DEPLOYMENT_FILE="deployment_production.txt"

# Function to check if deployment exists
check_deployment() {
    if [ ! -f "$DEPLOYMENT_FILE" ]; then
        echo -e "${RED}❌ No production deployment found${NC}"
        echo "Run ./deploy_production.sh first"
        exit 1
    fi
}

# Function to get instance IDs
get_instance_ids() {
    MODEL_ID=$(grep "Model Server" -A 2 "$DEPLOYMENT_FILE" | grep "ID:" | awk '{print $2}')
    API_ID=$(grep "API Server" -A 2 "$DEPLOYMENT_FILE" | grep "ID:" | awk '{print $2}')
}

# Function to get IPs
get_ips() {
    MODEL_IP=$(grep "Model Server" -A 2 "$DEPLOYMENT_FILE" | grep "IP:" | awk '{print $2}')
    API_IP=$(grep "API Server" -A 2 "$DEPLOYMENT_FILE" | grep "IP:" | awk '{print $2}')
}

# Main menu
show_menu() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║          Quant AI Production Management                   ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
    echo "1.  View deployment info"
    echo "2.  Check instance status"
    echo "3.  Start instances"
    echo "4.  Stop instances"
    echo "5.  Connect to model server (SSH)"
    echo "6.  Connect to API server (SSH)"
    echo "7.  View model server logs"
    echo "8.  View API server logs"
    echo "9.  Test model server"
    echo "10. Test API server"
    echo "11. Monitor GPU usage"
    echo "12. Check costs (current month)"
    echo "13. Restart model server"
    echo "14. Restart API server"
    echo "15. Deploy/Update backend code"
    echo "16. Run database migrations"
    echo "17. Backup database"
    echo "18. Complete teardown (DESTROY)"
    echo "19. Exit"
    echo ""
    read -p "Choose option (1-19): " choice
}

# Option handlers
view_info() {
    check_deployment
    echo ""
    echo "📊 Deployment Information:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    cat "$DEPLOYMENT_FILE"
}

check_status() {
    check_deployment
    get_instance_ids
    
    echo ""
    echo "🔍 Checking instance status..."
    aws ec2 describe-instances \
        --instance-ids $MODEL_ID $API_ID \
        --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name,PublicIpAddress,Tags[?Key==`Name`].Value|[0]]' \
        --output table
}

start_instances() {
    check_deployment
    get_instance_ids
    
    echo ""
    echo "🚀 Starting instances..."
    aws ec2 start-instances --instance-ids $MODEL_ID $API_ID
    
    echo ""
    echo "Waiting for instances to start..."
    aws ec2 wait instance-running --instance-ids $MODEL_ID $API_ID
    
    echo -e "${GREEN}✅ Instances started${NC}"
    echo ""
    echo "Note: IPs may have changed. Check deployment info."
}

stop_instances() {
    check_deployment
    get_instance_ids
    
    echo ""
    echo -e "${YELLOW}⚠️  This will stop both instances${NC}"
    echo "Cost after stopping: ~\$43/month (storage only)"
    echo ""
    read -p "Are you sure? (yes/no): " confirm
    
    if [ "$confirm" != "yes" ]; then
        echo "Cancelled"
        return
    fi
    
    echo ""
    echo "🛑 Stopping instances..."
    aws ec2 stop-instances --instance-ids $MODEL_ID $API_ID
    
    echo -e "${GREEN}✅ Instances stopping${NC}"
}

ssh_model() {
    check_deployment
    get_ips
    echo ""
    echo "Connecting to model server..."
    ssh -i ~/.ssh/id_rsa ubuntu@$MODEL_IP
}

ssh_api() {
    check_deployment
    get_ips
    echo ""
    echo "Connecting to API server..."
    ssh -i ~/.ssh/id_rsa ubuntu@$API_IP
}

view_model_logs() {
    check_deployment
    get_ips
    echo ""
    echo "Model server logs (Ctrl+C to exit):"
    ssh -i ~/.ssh/id_rsa ubuntu@$MODEL_IP 'tail -f ~/quantai-production/server.log'
}

view_api_logs() {
    check_deployment
    get_ips
    echo ""
    echo "API server logs (Ctrl+C to exit):"
    ssh -i ~/.ssh/id_rsa ubuntu@$API_IP 'tail -f ~/api.log'
}

test_model() {
    check_deployment
    get_ips
    
    echo ""
    echo "Testing model server..."
    echo ""
    echo "Health check:"
    curl -s http://$MODEL_IP:8001/health | python3 -m json.tool
    
    echo ""
    echo "Generation test:"
    curl -X POST http://$MODEL_IP:8001/generate \
        -H "Content-Type: application/json" \
        -H "X-API-Key: production-key-change-me" \
        -d '{"prompt": "Hello", "max_tokens": 20}' | python3 -m json.tool
}

test_api() {
    check_deployment
    get_ips
    
    echo ""
    echo "Testing API server..."
    curl -s http://$API_IP:8000/health | python3 -m json.tool
}

monitor_gpu() {
    check_deployment
    get_ips
    echo ""
    echo "GPU monitoring (Ctrl+C to exit):"
    ssh -i ~/.ssh/id_rsa ubuntu@$MODEL_IP 'watch -n 2 nvidia-smi'
}

check_costs() {
    echo ""
    echo "💰 Current month costs..."
    aws ce get-cost-and-usage \
        --time-period Start=$(date -u +%Y-%m-01),End=$(date -u +%Y-%m-%d) \
        --granularity MONTHLY \
        --metrics BlendedCost \
        --group-by Type=SERVICE
}

restart_model() {
    check_deployment
    get_ips
    
    echo ""
    echo "Restarting model server..."
    ssh -i ~/.ssh/id_rsa ubuntu@$MODEL_IP << 'SSH'
cd ~/quantai-production
if [ -f server.pid ]; then
    kill $(cat server.pid) || true
    sleep 2
fi
./start_server.sh
SSH
    echo -e "${GREEN}✅ Model server restarted${NC}"
}

restart_api() {
    check_deployment
    get_ips
    
    echo ""
    echo "Restarting API server..."
    ssh -i ~/.ssh/id_rsa ubuntu@$API_IP << 'SSH'
pkill -f "uvicorn backend.api.main:app" || true
sleep 2
cd ~
source venv/bin/activate
nohup uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 > api.log 2>&1 &
SSH
    echo -e "${GREEN}✅ API server restarted${NC}"
}

deploy_backend() {
    check_deployment
    get_ips
    
    echo ""
    echo "Deploying backend code to API server..."
    
    # Create package
    tar czf backend-update.tar.gz backend/ config/ requirements.txt
    
    # Upload
    scp -i ~/.ssh/id_rsa backend-update.tar.gz ubuntu@$API_IP:~/
    
    # Extract and restart
    ssh -i ~/.ssh/id_rsa ubuntu@$API_IP << 'SSH'
tar xzf backend-update.tar.gz
source venv/bin/activate
pip install -r requirements.txt
pkill -f "uvicorn backend.api.main:app" || true
sleep 2
nohup uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 > api.log 2>&1 &
SSH
    
    rm backend-update.tar.gz
    echo -e "${GREEN}✅ Backend deployed and restarted${NC}"
}

run_migrations() {
    check_deployment
    get_ips
    
    echo ""
    echo "Running database migrations..."
    ssh -i ~/.ssh/id_rsa ubuntu@$API_IP << 'SSH'
cd ~
source venv/bin/activate
python -m alembic upgrade head
SSH
    echo -e "${GREEN}✅ Migrations complete${NC}"
}

backup_database() {
    check_deployment
    
    RDS_ENDPOINT=$(grep "Endpoint:" "$DEPLOYMENT_FILE" | awk '{print $2}')
    BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql"
    
    echo ""
    echo "Creating database backup..."
    get_ips
    
    ssh -i ~/.ssh/id_rsa ubuntu@$API_IP << SSH
pg_dump -h $RDS_ENDPOINT -U quantai -d quantai_db > ~/$BACKUP_FILE
gzip ~/$BACKUP_FILE
SSH
    
    # Download backup
    scp -i ~/.ssh/id_rsa ubuntu@$API_IP:~/${BACKUP_FILE}.gz ./
    
    echo -e "${GREEN}✅ Backup saved: ${BACKUP_FILE}.gz${NC}"
}

destroy_deployment() {
    check_deployment
    
    echo ""
    echo -e "${RED}⚠️  WARNING: PERMANENT DESTRUCTION ⚠️${NC}"
    echo ""
    echo "This will DELETE:"
    echo "  - All EC2 instances"
    echo "  - RDS database"
    echo "  - S3 buckets and data"
    echo "  - All security groups and networking"
    echo ""
    echo -e "${RED}THIS CANNOT BE UNDONE!${NC}"
    echo ""
    read -p "Type 'DELETE' to confirm: " confirm
    
    if [ "$confirm" != "DELETE" ]; then
        echo "Cancelled"
        return
    fi
    
    echo ""
    echo "🔥 Destroying infrastructure..."
    cd infrastructure/terraform
    terraform destroy -auto-approve
    cd ../..
    
    rm -f "$DEPLOYMENT_FILE"
    
    echo -e "${GREEN}✅ All resources destroyed${NC}"
}

# Main loop
while true; do
    show_menu
    
    case $choice in
        1) view_info ;;
        2) check_status ;;
        3) start_instances ;;
        4) stop_instances ;;
        5) ssh_model ;;
        6) ssh_api ;;
        7) view_model_logs ;;
        8) view_api_logs ;;
        9) test_model ;;
        10) test_api ;;
        11) monitor_gpu ;;
        12) check_costs ;;
        13) restart_model ;;
        14) restart_api ;;
        15) deploy_backend ;;
        16) run_migrations ;;
        17) backup_database ;;
        18) destroy_deployment ;;
        19) echo "Goodbye!"; exit 0 ;;
        *) echo "Invalid option" ;;
    esac
    
    echo ""
    read -p "Press Enter to continue..."
done
