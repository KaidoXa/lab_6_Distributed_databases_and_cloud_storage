# Отримуємо свіжий образ Amazon Linux 2023 AMI
data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

# 1. EC2 Склад (Warehouse)
resource "aws_instance" "warehouse" {
  ami                  = data.aws_ami.amazon_linux_2023.id
  instance_type        = "t3.micro"
  key_name             = var.key_name != "" ? var.key_name : null
  iam_instance_profile = "LabInstanceProfile"
  vpc_security_group_ids = [aws_security_group.warehouse_sg.id]

  user_data = <<-EOF
              #!/bin/bash
              dnf update -y
              dnf install -y python3 python3-pip git

              mkdir -p /app
              cd /app

              git clone ${var.github_repo_url} repo
              cp -r repo/warehouse/* /app/
              cp repo/requirements.txt /app/

              pip3 install -r requirements.txt

              echo "NAIVE_MODE=false" > /etc/warehouse.env

              cat <<EOT > /etc/systemd/system/warehouse.service
              [Unit]
              Description=Warehouse Microservice
              After=network.target

              [Service]
              User=root
              WorkingDirectory=/app
              Environment="DB_HOST=${aws_db_instance.mysql.address}"
              Environment="DB_PORT=3306"
              Environment="DB_USER=admin"
              Environment="DB_PASSWORD=${var.db_password}"
              Environment="DB_NAME=warehouse"
              Environment="PYTHONUNBUFFERED=1"
              EnvironmentFile=-/etc/warehouse.env
              ExecStart=/usr/local/bin/uvicorn main:app --host 0.0.0.0 --port 8081
              Restart=always
              RestartSec=3

              [Install]
              WantedBy=multi-user.target
              EOT

              systemctl daemon-reload
              systemctl enable warehouse
              systemctl start warehouse
              EOF

  tags = {
    Name = "lab6-warehouse-ec2"
  }
}

# 2. EC2 Банк (Bank)
resource "aws_instance" "bank" {
  ami                  = data.aws_ami.amazon_linux_2023.id
  instance_type        = "t3.micro"
  key_name             = var.key_name != "" ? var.key_name : null
  iam_instance_profile = "LabInstanceProfile"
  vpc_security_group_ids = [aws_security_group.bank_sg.id]

  user_data = <<-EOF
              #!/bin/bash
              dnf update -y
              dnf install -y python3 python3-pip git

              mkdir -p /app
              cd /app

              git clone ${var.github_repo_url} repo
              cp -r repo/bank/* /app/
              cp repo/requirements.txt /app/

              pip3 install -r requirements.txt

              cat <<EOT > /etc/systemd/system/bank.service
              [Unit]
              Description=Bank Microservice
              After=network.target

              [Service]
              User=root
              WorkingDirectory=/app
              Environment="DB_HOST=${aws_db_instance.mysql.address}"
              Environment="DB_PORT=3306"
              Environment="DB_USER=admin"
              Environment="DB_PASSWORD=${var.db_password}"
              Environment="DB_NAME=bank"
              Environment="PYTHONUNBUFFERED=1"
              ExecStart=/usr/local/bin/uvicorn main:app --host 0.0.0.0 --port 8082
              Restart=always
              RestartSec=3

              [Install]
              WantedBy=multi-user.target
              EOT

              systemctl daemon-reload
              systemctl enable bank
              systemctl start bank
              EOF

  tags = {
    Name = "lab6-bank-ec2"
  }
}

# 3. EC2 Магазин (Shop Coordinator)
resource "aws_instance" "shop" {
  ami                  = data.aws_ami.amazon_linux_2023.id
  instance_type        = "t3.micro"
  key_name             = var.key_name != "" ? var.key_name : null
  iam_instance_profile = "LabInstanceProfile"
  vpc_security_group_ids = [aws_security_group.shop_sg.id]

  user_data = <<-EOF
              #!/bin/bash
              dnf update -y
              dnf install -y python3 python3-pip git mariadb105

              mkdir -p /app
              cd /app

              git clone ${var.github_repo_url} repo
              cp -r repo/shop/* /app/
              cp repo/requirements.txt /app/

              pip3 install -r requirements.txt

              echo "DECISION_DELAY=0" > /etc/shop.env

              cat <<EOT > /etc/systemd/system/shop.service
              [Unit]
              Description=Shop Coordinator Microservice
              After=network.target

              [Service]
              User=root
              WorkingDirectory=/app
              Environment="DB_HOST=${aws_db_instance.mysql.address}"
              Environment="DB_PORT=3306"
              Environment="DB_USER=admin"
              Environment="DB_PASSWORD=${var.db_password}"
              Environment="DB_NAME=shop"
              Environment="PYTHONUNBUFFERED=1"
              Environment="WAREHOUSE_URL=http://${aws_instance.warehouse.private_ip}:8081"
              Environment="BANK_URL=http://${aws_instance.bank.private_ip}:8082"
              Environment="S3_BUCKET=${local.bucket_name}"
              Environment="AWS_REGION=${var.aws_region}"
              EnvironmentFile=-/etc/shop.env
              ExecStart=/usr/local/bin/uvicorn main:app --host 0.0.0.0 --port 8080
              Restart=always
              RestartSec=3

              [Install]
              WantedBy=multi-user.target
              EOT

              systemctl daemon-reload
              systemctl enable shop
              systemctl start shop
              EOF

  depends_on = [
    aws_instance.warehouse,
    aws_instance.bank,
    aws_db_instance.mysql,
    null_resource.create_s3_bucket
  ]

  tags = {
    Name = "lab6-shop-ec2"
  }
}
