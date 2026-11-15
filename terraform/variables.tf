variable "aws_region" {
  description = "AWS Region for AWS Academy Learner Lab"
  type        = string
  default     = "us-east-1"
}

variable "my_ip" {
  description = "Your personal IP address for SSH access (CIDR format: x.x.x.x/32)"
  type        = string
  default     = "0.0.0.0/0"
}

variable "key_name" {
  description = "Optional EC2 Key Pair name if you want to connect via SSH"
  type        = string
  default     = "vockey" # Стандартний ключ у Learner Lab або залиште порожнім
}

variable "github_repo_url" {
  description = "Git repository URL containing the lab code"
  type        = string
  default     = "" # Вкажете свій URL репозиторію
}

variable "db_password" {
  description = "Master password for RDS MySQL"
  type        = string
  default     = "Lab6Password123!"
}
