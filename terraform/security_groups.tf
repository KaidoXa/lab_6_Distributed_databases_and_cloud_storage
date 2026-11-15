# Використовуємо Default VPC та її публічні підмережі для простоти розгортання в Learner Lab
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# 1. Security Group для Магазину (Shop)
# Доступний з інтернету на порту 8080, SSH з власного IP
resource "aws_security_group" "shop_sg" {
  name        = "lab6-shop-sg"
  description = "Security group for Shop coordinator service"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP API access"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH access"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "lab6-shop-sg"
  }
}

# 2. Security Group для Складу (Warehouse)
# Порт 8081 відкритий ТІЛЬКИ для Security Group Магазину
resource "aws_security_group" "warehouse_sg" {
  name        = "lab6-warehouse-sg"
  description = "Security group for Warehouse service"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Internal API access from Shop"
    from_port       = 8081
    to_port         = 8081
    protocol        = "tcp"
    security_groups = [aws_security_group.shop_sg.id]
  }

  ingress {
    description = "SSH access"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "lab6-warehouse-sg"
  }
}

# 3. Security Group для Банку (Bank)
# Порт 8082 відкритий ТІЛЬКИ для Security Group Магазину
resource "aws_security_group" "bank_sg" {
  name        = "lab6-bank-sg"
  description = "Security group for Bank service"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Internal API access from Shop"
    from_port       = 8082
    to_port         = 8082
    protocol        = "tcp"
    security_groups = [aws_security_group.shop_sg.id]
  }

  ingress {
    description = "SSH access"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "lab6-bank-sg"
  }
}

# 4. Security Group для RDS MySQL
# Порт 3306 відкритий ТІЛЬКИ для Security Groups трьох сервісів
resource "aws_security_group" "rds_sg" {
  name        = "lab6-rds-sg"
  description = "Security group for RDS MySQL"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "MySQL from Shop"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.shop_sg.id]
  }

  ingress {
    description     = "MySQL from Warehouse"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.warehouse_sg.id]
  }

  ingress {
    description     = "MySQL from Bank"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.bank_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "lab6-rds-sg"
  }
}
