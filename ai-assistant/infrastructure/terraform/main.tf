# Terraform configuration for AWS infrastructure
terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  
  backend "s3" {
    bucket = "quantai-terraform-state"
    key    = "terraform.tfstate"
    region = "us-east-1"
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region
}

# Variables
variable "aws_region" {
  description = "AWS region"
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name"
  default     = "quantai"
}

variable "environment" {
  description = "Environment (dev/prod)"
  default     = "dev"
}

variable "model_instance_type" {
  description = "EC2 instance type for model server"
  default     = "g4dn.xlarge"  # 1x NVIDIA T4 GPU
}

variable "api_instance_type" {
  description = "EC2 instance type for API server"
  default     = "t3.medium"
}

variable "your_ip" {
  description = "Your IP address for SSH access"
  type        = string
}

# VPC Configuration
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  
  tags = {
    Name        = "${var.project_name}-vpc"
    Environment = var.environment
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  
  tags = {
    Name = "${var.project_name}-igw"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = true
  
  tags = {
    Name = "${var.project_name}-public-subnet"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  
  tags = {
    Name = "${var.project_name}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Security Groups
resource "aws_security_group" "model_server" {
  name        = "${var.project_name}-model-server-sg"
  description = "Security group for model server"
  vpc_id      = aws_vpc.main.id
  
  # SSH access from your IP only
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.your_ip]
  }
  
  # Model API access from API server
  ingress {
    from_port       = 8001
    to_port         = 8001
    protocol        = "tcp"
    security_groups = [aws_security_group.api_server.id]
  }
  
  # Outbound internet access
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = {
    Name = "${var.project_name}-model-server-sg"
  }
}

resource "aws_security_group" "api_server" {
  name        = "${var.project_name}-api-server-sg"
  description = "Security group for API server"
  vpc_id      = aws_vpc.main.id
  
  # SSH access
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.your_ip]
  }
  
  # HTTPS access from anywhere
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  # HTTP access (redirect to HTTPS)
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  # API port
  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = {
    Name = "${var.project_name}-api-server-sg"
  }
}

# S3 Bucket for storage
resource "aws_s3_bucket" "storage" {
  bucket = "${var.project_name}-storage-${var.environment}"
  
  tags = {
    Name        = "${var.project_name}-storage"
    Environment = var.environment
  }
}

resource "aws_s3_bucket_versioning" "storage" {
  bucket = aws_s3_bucket.storage.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "storage" {
  bucket = aws_s3_bucket.storage.id
  
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# IAM Role for EC2 instances
resource "aws_iam_role" "ec2_role" {
  name = "${var.project_name}-ec2-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "ec2_policy" {
  name = "${var.project_name}-ec2-policy"
  role = aws_iam_role.ec2_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.storage.arn,
          "${aws_s3_bucket.storage.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData",
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.ec2_role.name
}

# Model Server EC2 Instance
resource "aws_instance" "model_server" {
  ami           = data.aws_ami.deep_learning.id
  instance_type = var.model_instance_type
  subnet_id     = aws_subnet.public.id
  
  vpc_security_group_ids = [aws_security_group.model_server.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2_profile.name
  
  root_block_device {
    volume_size = 100
    volume_type = "gp3"
  }
  
  user_data = file("${path.module}/scripts/model_server_init.sh")
  
  tags = {
    Name        = "${var.project_name}-model-server"
    Environment = var.environment
    Type        = "model-server"
  }
}

# API Server EC2 Instance
resource "aws_instance" "api_server" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = var.api_instance_type
  subnet_id     = aws_subnet.public.id
  
  vpc_security_group_ids = [aws_security_group.api_server.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2_profile.name
  
  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }
  
  user_data = file("${path.module}/scripts/api_server_init.sh")
  
  tags = {
    Name        = "${var.project_name}-api-server"
    Environment = var.environment
    Type        = "api-server"
  }
}

# Data sources for AMIs
data "aws_ami" "deep_learning" {
  most_recent = true
  owners      = ["amazon"]
  
  filter {
    name   = "name"
    values = ["Deep Learning AMI GPU PyTorch *"]
  }
  
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]  # Canonical
  
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-22.04-amd64-server-*"]
  }
}

# CloudWatch Log Groups
resource "aws_cloudwatch_log_group" "model_server" {
  name              = "/aws/ec2/${var.project_name}-model-server"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "api_server" {
  name              = "/aws/ec2/${var.project_name}-api-server"
  retention_in_days = 30
}

# Outputs
output "model_server_ip" {
  value       = aws_instance.model_server.public_ip
  description = "Public IP of model server"
}

output "api_server_ip" {
  value       = aws_instance.api_server.public_ip
  description = "Public IP of API server"
}

output "s3_bucket" {
  value       = aws_s3_bucket.storage.bucket
  description = "S3 bucket name"
}

output "model_server_url" {
  value       = "http://${aws_instance.model_server.private_ip}:8001"
  description = "Model server URL (internal)"
}
