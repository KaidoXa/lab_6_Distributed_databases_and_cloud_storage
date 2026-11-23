terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # Вимикаємо виклики S3 API, які блокуються політиками AWS Academy SCP
  skip_requesting_account_id = false
  
  # Не перевіряти Object Lock і ACL
  default_tags {
    tags = {
      Environment = "Lab6"
    }
  }
}
