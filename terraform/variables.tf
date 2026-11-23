variable "aws_region" {
  description = "AWS Region for AWS Academy Learner Lab"
  type        = string
  default     = "us-east-1"
}

variable "my_ip" {
  description = "IP адреса для SSH у форматі x.x.x.x/32 (без значення за замовчуванням, див. TF_VAR_my_ip)"
  type        = string

  validation {
    condition     = can(cidrnetmask(var.my_ip)) && var.my_ip != "0.0.0.0/0"
    error_message = "my_ip має бути коректним CIDR (наприклад 203.0.113.5/32), але не 0.0.0.0/0."
  }
}

variable "key_name" {
  description = "EC2 Key Pair для SSH (у Learner Lab стандартний vockey)"
  type        = string
  default     = "vockey"
}

variable "github_repo_url" {
  description = "Git repository URL containing the lab code"
  type        = string
  default     = "https://github.com/KaidoXa/lab_6_Distributed_databases_and_cloud_storage.git"
}

variable "db_password" {
  description = "Master password for RDS MySQL (передається через TF_VAR_db_password)"
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[A-Za-z0-9_-]{8,41}$", var.db_password))
    error_message = "Пароль: 8-41 символів, лише літери, цифри, _ і -."
  }
}
