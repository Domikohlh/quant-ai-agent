provider "aws" {
  region = "us-west-2"
}

# S3 bucket for models
resource "aws_s3_bucket" "models" {
  bucket = "your-unique-ai-models-bucket"
  
  tags = {
    Name = "AI Assistant Models"
  }
}

# EC2 instance for model serving
resource "aws_instance" "model_server" {
  ami           = "ami-0c55b159cbfafe1f0"  # Deep Learning AMI
  instance_type = "g5.xlarge"
  
  tags = {
    Name = "AI Model Server"
  }
  
  # Security group allowing only your IP
  vpc_security_group_ids = [aws_security_group.model_server.id]
}

# Security group
resource "aws_security_group" "model_server" {
  name = "model-server-sg"
  
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["YOUR_IP/32"]  # Replace with your IP
  }
}
