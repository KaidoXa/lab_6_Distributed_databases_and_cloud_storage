output "shop_public_ip" {
  description = "Public IP address of the Shop Coordinator"
  value       = aws_instance.shop.public_ip
}

output "shop_url" {
  description = "Public URL for Shop API"
  value       = "http://${aws_instance.shop.public_ip}:8080"
}

output "warehouse_private_ip" {
  description = "Private IP address of Warehouse service"
  value       = aws_instance.warehouse.private_ip
}

output "bank_private_ip" {
  description = "Private IP address of Bank service"
  value       = aws_instance.bank.private_ip
}

output "rds_endpoint" {
  description = "Endpoint address of RDS MySQL"
  value       = aws_db_instance.mysql.address
}

output "s3_bucket_name" {
  description = "Name of the created S3 Receipts bucket"
  value       = local.bucket_name
}
