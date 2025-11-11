# Quant AI - Intelligent Quantitative Finance Assistant

A sophisticated AI-powered quantitative finance assistant with dynamic model switching, real-time market monitoring, and advanced trading capabilities. Built for private use with hybrid cloud-local architecture.

## 🎯 Project Status: Steps 1-3 Complete

✅ **Step 1: Project Structure & Configuration** - Complete
✅ **Step 2: AWS Deployment Setup** - Complete  
✅ **Step 3: Model Deployment & Inference** - Complete

### Completed Components

- ✅ Complete directory structure
- ✅ Docker configuration (API + Model server)
- ✅ Environment configuration system
- ✅ AWS Terraform infrastructure
- ✅ Model inference server (GPU-accelerated)
- ✅ Dynamic model switching logic
- ✅ Structured logging system
- ✅ Database configuration
- ✅ FastAPI application framework
- ✅ Deployment scripts

### Next Steps (Upcoming)

- ⏳ Step 4: API Integrations (Alpaca, Google, Interactive Brokers)
- ⏳ Step 5: RAG System Implementation
- ⏳ Step 6: Trading Engine Development
- ⏳ Step 7: Monitoring & Logging Services
- ⏳ Step 8: Frontend Development (SwiftUI)

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                  CLIENT LAYER (SwiftUI)                  │
│        iPhone │ MacBook │ iPad                          │
└────────────────────┬────────────────────────────────────┘
                     │ REST API / WebSocket
┌────────────────────┼────────────────────────────────────┐
│            FastAPI Gateway (AWS EC2)                     │
│  ┌──────────┬──────────┬──────────┬───────────┐        │
│  │ Trading  │Portfolio │Backtesting│  News    │        │
│  │ Engine   │Analyzer  │ System   │ Monitor  │        │
│  └──────────┴──────────┴──────────┴───────────┘        │
└────────────────────┬───────────┬────────────────────────┘
                     │           │
         ┌───────────┴──┐    ┌───┴────────────┐
         │ AWS GPU EC2  │    │ Local Fallback │
         │ GPT-OSS-20B  │    │ Llama 3.2 3B  │
         └──────────────┘    └────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- AWS Account (for production deployment)
- Git
- 50GB+ disk space (for models)

### 1. Initial Setup

```bash
# Clone repository
cd ai-assistant

# Run initialization script
chmod +x scripts/init_project.sh
./scripts/init_project.sh

# This will:
# - Create directory structure
# - Set up virtual environment
# - Install dependencies
# - Configure Docker
# - Initialize database
```

### 2. Configure Environment

```bash
# Edit .env file with your API keys
nano .env

# Required keys:
# - ALPACA_API_KEY / ALPACA_SECRET_KEY
# - GOOGLE_API_KEY / GOOGLE_CX
# - IB_ACCOUNT (Interactive Brokers)
# - SECRET_KEY (generate with: openssl rand -hex 32)
```

### 3. Start Local Development

```bash
# Activate virtual environment
source ../ai-assistant-env/bin/activate

# Start services
docker-compose up -d

# Run API server
python -m uvicorn backend.api.main:app --reload

# Access API documentation
open http://localhost:8000/docs
```

## 📦 Project Structure

```
ai-assistant/
├── backend/
│   ├── api/                    # FastAPI routes and middleware
│   │   ├── routes/            # API endpoints
│   │   ├── middleware/        # Custom middleware
│   │   └── schemas/           # Pydantic models
│   ├── core/                  # Core configuration
│   │   ├── config/           # Settings management
│   │   ├── security/         # Authentication & authorization
│   │   └── database.py       # Database setup
│   ├── models/               # AI models
│   │   ├── llm/             # LLM inference & management
│   │   ├── rag/             # RAG system
│   │   └── local/           # Local model handling
│   ├── services/            # Business logic
│   │   ├── trading/         # Trading strategies & execution
│   │   ├── monitoring/      # Price & news monitoring
│   │   ├── portfolio/       # Portfolio analysis
│   │   └── news/            # News processing
│   ├── utils/               # Utilities
│   │   ├── logging/         # Structured logging
│   │   ├── metrics/         # Prometheus metrics
│   │   └── validators/      # Input validation
│   └── tests/               # Test suite
├── data/
│   ├── models/              # Downloaded models
│   ├── vectors/             # ChromaDB vector storage
│   ├── logs/                # Application logs
│   └── backtest_results/    # Backtesting outputs
├── docker/
│   ├── api/                 # API server Dockerfile
│   ├── model/               # Model server Dockerfile
│   └── postgres/            # Database initialization
├── infrastructure/
│   └── terraform/           # AWS infrastructure as code
├── scripts/
│   ├── deployment/          # Deployment scripts
│   ├── backup/              # Backup utilities
│   └── migration/           # Database migrations
├── config/                  # Configuration files
├── frontend/               # SwiftUI apps (upcoming)
│   ├── ios/
│   ├── macos/
│   └── shared/
└── docs/                   # Documentation
```

## 🔧 Technology Stack

### Backend
- **Framework**: FastAPI (async Python web framework)
- **Database**: PostgreSQL + TimescaleDB (time-series data)
- **Cache**: Redis
- **Task Queue**: Celery + Redis
- **AI/ML**: PyTorch, Transformers, LangChain
- **Vector DB**: ChromaDB
- **Monitoring**: Prometheus + Grafana

### Frontend (Upcoming)
- **Framework**: SwiftUI
- **Platforms**: iOS 17+, macOS 14+, iPadOS 17+
- **Charts**: Swift Charts
- **Storage**: SwiftData
- **Networking**: URLSession + Combine

### Infrastructure
- **Cloud**: AWS (EC2, S3, CloudWatch)
- **Containers**: Docker + Docker Compose
- **IaC**: Terraform
- **CI/CD**: GitHub Actions

### APIs
- **Market Data**: Alpaca API
- **Trading**: Interactive Brokers API
- **News**: Google JSON API
- **AI Models**: Self-hosted (HuggingFace)

## 🤖 Model Architecture

### Primary Model (AWS)
- **Model**: GPT-OSS-20B (or equivalent)
- **Hardware**: AWS EC2 g4dn.xlarge (NVIDIA T4 GPU)
- **Quantization**: 4-bit (bitsandbytes)
- **Use Cases**: Trading decisions, complex analysis, critical events

### Local Fallback Model
- **Model**: Llama 3.2 3B Instruct
- **Hardware**: On-device (CPU/GPU)
- **Quantization**: 4-bit
- **Use Cases**: Simple queries, offline mode, cost optimization

### Dynamic Switching Logic
```python
# Automatically switches based on:
- Query complexity
- News sentiment (critical_news_threshold: 0.8)
- Price volatility (>2%)
- Idle time (>30 minutes)
- AWS availability
```

## 📊 Features

### ✅ Completed
- [x] Dynamic model switching (AWS ↔ Local)
- [x] Structured logging with hallucination tracking
- [x] Docker containerization
- [x] AWS infrastructure setup
- [x] Database configuration
- [x] API framework

### 🔄 In Progress
- [ ] Alpaca API integration
- [ ] Interactive Brokers integration
- [ ] Google News API integration
- [ ] RAG system for financial knowledge
- [ ] Trading strategy framework

### 📋 Planned
- [ ] Paper trading system
- [ ] Live trading (with HITL approval)
- [ ] Portfolio analyzer
- [ ] Backtesting engine
- [ ] Real-time price monitoring
- [ ] News sentiment analysis
- [ ] SwiftUI frontend apps
- [ ] Push notifications

## 🚢 Deployment

### Local Development
```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop services
docker-compose down
```

### AWS Production
```bash
# Deploy infrastructure
cd infrastructure/terraform
terraform init
terraform plan
terraform apply

# Deploy application
cd ../..
./scripts/deployment/deploy_aws.sh
```

### Model Deployment
```bash
# Download models
python scripts/deployment/download_models.py

# Upload to S3
aws s3 sync data/models/ s3://your-bucket/models/
```

## 💰 Cost Estimation

### 24/7 Operation
| Component | Cost/Month |
|-----------|------------|
| AWS EC2 (GPU) | $285 |
| AWS EC2 (API) | $30 |
| RDS PostgreSQL | $25 |
| S3 Storage | $2-10 |
| Data Transfer | $90 |
| **Total** | **~$450/month** |

### Optimized (Recommended)
| Optimization | Savings | New Cost |
|--------------|---------|----------|
| Spot Instances | 70% | $85 (GPU) |
| Market Hours Only | 50% | $140 (GPU) |
| Aggressive Local Mode | 60% | ~$180/month |

## 🔐 Security

- ✅ API key authentication
- ✅ JWT tokens for sessions
- ✅ Encrypted secrets (AWS Secrets Manager)
- ✅ TLS/SSL for all communications
- ✅ Human-in-the-loop for all trades
- ✅ Rate limiting
- ✅ Input validation
- ✅ Audit logging

## 🧪 Testing

```bash
# Run all tests
pytest backend/tests/ -v

# Run with coverage
pytest backend/tests/ --cov=backend --cov-report=html

# Run specific test
pytest backend/tests/unit/test_models.py -v

# Linting
black backend/ --check
flake8 backend/
```

## 📝 API Documentation

Once the server is running:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI Schema**: http://localhost:8000/openapi.json

## 🔍 Monitoring

- **API Logs**: `data/logs/api/`
- **Trading Logs**: `data/logs/trading/`
- **Error Logs**: `data/logs/errors/`
- **Hallucination Logs**: `data/logs/model/hallucinations.jsonl`
- **Celery Dashboard**: http://localhost:5555
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000

## 🐛 Troubleshooting

### Model Server Won't Start
```bash
# Check GPU availability
nvidia-smi

# Check model files
ls -lh data/models/

# View logs
docker logs quantai_model -f
```

### Database Connection Failed
```bash
# Check PostgreSQL
docker-compose ps postgres

# Reset database
docker-compose down -v
docker-compose up -d postgres
python -m alembic upgrade head
```

### API Key Errors
```bash
# Verify .env file
cat .env | grep API_KEY

# Test API connection
curl -X GET "https://paper-api.alpaca.markets/v2/account" \
  -H "APCA-API-KEY-ID: YOUR_KEY" \
  -H "APCA-API-SECRET-KEY: YOUR_SECRET"
```

## 📚 Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Alpaca API Docs](https://alpaca.markets/docs/)
- [Interactive Brokers API](https://interactivebrokers.github.io/)
- [HuggingFace Transformers](https://huggingface.co/docs/transformers)
- [SwiftUI Documentation](https://developer.apple.com/xcode/swiftui/)

## 🤝 Contributing

This is a private project. For any issues or questions, please document them in `docs/issues.md`.

## 📄 License

Private use only. Not for distribution.

## 🙏 Acknowledgments

- OpenAI for GPT architecture research
- HuggingFace for model hosting
- Alpaca for free market data API
- Meta for Llama models

---

**Current Version**: 1.0.0-alpha  
**Last Updated**: November 2025  
**Status**: Backend Development (Steps 1-3 Complete)
