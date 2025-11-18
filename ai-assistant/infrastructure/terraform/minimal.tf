# Minimal Terraform configuration for testing only
# This creates the smallest possible setup for testing model inference
# Estimated cost: ~$0.50/hour (~$12/day if left running)

terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
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

variable "your_ip" {
  description = "Your IP address for SSH access (format: x.x.x.x/32)"
  type        = string
}

variable "enable_model_server" {
  description = "Enable GPU model server (expensive, ~$0.50/hr)"
  type        = bool
  default     = false
}

# Get latest Deep Learning AMI
data "aws_ami" "deep_learning" {
  most_recent = true
  
    filter {
    name   = "name"
    values = ["Deep Learning AMI*"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }

  owners = ["amazon"]
}

# Get latest Ubuntu AMI
data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  owners = ["099720109477"] # Canonical
}


# S3 Bucket for models and logs
resource "aws_s3_bucket" "quantai_test" {
  bucket = "quantai-test-${random_id.bucket_suffix.hex}"
  
  tags = {
    Name        = "quantai-test-bucket"
    Environment = "test"
    Project     = "QuantAI"
  }
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket_versioning" "quantai_test" {
  bucket = aws_s3_bucket.quantai_test.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

# Security Group
resource "aws_security_group" "test_sg" {
  name        = "quantai-test-sg"
  description = "Security group for Quant AI test"
  
  # SSH from your IP only
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.your_ip]
    description = "SSH from your IP"
  }
  
  # Model server API (if enabled)
  ingress {
    from_port   = 8001
    to_port     = 8001
    protocol    = "tcp"
    cidr_blocks = [var.your_ip]
    description = "Model server API"
  }
  
  # Outbound internet access
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = {
    Name = "quantai-test-sg"
  }
}

# IAM Role for EC2
resource "aws_iam_role" "test_role" {
  name = "quantai-test-ec2-role"
  
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

resource "aws_iam_role_policy" "test_policy" {
  name = "quantai-test-policy"
  role = aws_iam_role.test_role.id
  
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
          aws_s3_bucket.quantai_test.arn,
          "${aws_s3_bucket.quantai_test.arn}/*"
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

resource "aws_iam_instance_profile" "test_profile" {
  name = "quantai-test-profile"
  role = aws_iam_role.test_role.name
}

# SSH Key Pair
resource "aws_key_pair" "test_key" {
  key_name   = "quantai-test-key"
  public_key = file(pathexpand("~/.ssh/id_rsa.pub"))
}

# Model Server (Optional - EXPENSIVE)
resource "aws_instance" "model_server" {
  count = var.enable_model_server ? 1 : 0
  
  ami           = data.aws_ami.deep_learning.id
  instance_type = "g4dn.xlarge"  # ~$0.526/hour
  
  vpc_security_group_ids = [aws_security_group.test_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.test_profile.name
  key_name               = aws_key_pair.test_key.key_name
  
  root_block_device {
    volume_size = 100
    volume_type = "gp3"
  }
  
  user_data = <<-EOF
              #!/bin/bash
              echo "Quant AI Model Server - Test Instance" > /home/ubuntu/README.txt
              echo "Instance started at: $(date)" >> /home/ubuntu/README.txt
              
              # Install Docker
              apt-get update
              apt-get install -y docker.io
              systemctl start docker
              systemctl enable docker
              usermod -aG docker ubuntu
              
              # Create marker file
              touch /home/ubuntu/model-server-ready
              EOF
  
  tags = {
    Name        = "quantai-model-server-test"
    Environment = "test"
    CostCenter  = "high-priority-stop"
  }
}

# Cheap Test Instance (Always created)
resource "aws_instance" "test_instance" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = "t3.micro"  # ~$0.0104/hour (FREE TIER eligible)
  
  vpc_security_group_ids = [aws_security_group.test_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.test_profile.name
  key_name               = aws_key_pair.test_key.key_name
  
  user_data = <<-EOF
              #!/bin/bash
              echo "Quant AI Test Instance" > /home/ubuntu/README.txt
              echo "Instance started at: $(date)" >> /home/ubuntu/README.txt
              
              # Install basic tools
              apt-get update
              apt-get install -y python3 python3-pip docker.io
              
              touch /home/ubuntu/test-instance-ready
              EOF
  
  tags = {
    Name        = "quantai-test-instance"
    Environment = "test"
  }
}

# Outputs
output "test_instance_ip" {
  value       = aws_instance.test_instance.public_ip
  description = "IP of test instance (t3.micro - cheap)"
}

output "test_instance_id" {
  value       = aws_instance.test_instance.id
  description = "Instance ID for test instance"
}

output "model_server_ip" {
  value       = var.enable_model_server ? aws_instance.model_server[0].public_ip : "Not deployed"
  description = "IP of model server (g4dn.xlarge - expensive)"
}

output "model_server_id" {
  value       = var.enable_model_server ? aws_instance.model_server[0].id : "Not deployed"
  description = "Instance ID for model server"
}

output "s3_bucket" {
  value       = aws_s3_bucket.quantai_test.bucket
  description = "S3 bucket name"
}

output "ssh_command_test" {
  value       = "ssh -i ~/.ssh/id_rsa ubuntu@${aws_instance.test_instance.public_ip}"
  description = "SSH command for test instance"
}

output "ssh_command_model" {
  value       = var.enable_model_server ? "ssh -i ~/.ssh/id_rsa ubuntu@${aws_instance.model_server[0].public_ip}" : "Model server not deployed"
  description = "SSH command for model server"
}

output "cost_estimate" {
  value = var.enable_model_server ? "~$0.53/hour (~$13/day with model server)" : "~$0.01/hour (~$0.25/day - FREE TIER eligible)"
  description = "Estimated hourly cost"
}
