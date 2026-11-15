resource "aws_db_subnet_group" "rds_subnet_group" {
  name       = "lab6-rds-subnet-group"
  subnet_ids = data.aws_subnets.default.ids

  tags = {
    Name = "lab6-rds-subnet-group"
  }
}

resource "aws_db_instance" "mysql" {
  identifier             = "lab6-mysql-db"
  allocated_storage      = 20
  max_allocated_storage  = 20
  engine                 = "mysql"
  engine_version         = "8.0"
  instance_class         = "db.t3.micro"
  db_name                = "shop" # Початкова база даних
  username               = "admin"
  password               = var.db_password
  parameter_group_name   = "default.mysql8.0"
  skip_final_snapshot    = true
  publicly_accessible    = false
  multi_az               = false # Суворе обмеження AWS Academy: тільки Single-AZ
  vpc_security_group_ids = [aws_security_group.rds_sg.id]
  db_subnet_group_name   = aws_db_subnet_group.rds_subnet_group.name

  tags = {
    Name = "lab6-rds-mysql"
  }
}
