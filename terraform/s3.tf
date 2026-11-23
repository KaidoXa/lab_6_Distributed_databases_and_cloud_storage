# Генератор випадкового суфіксу для унікального імені бакета S3
resource "random_id" "bucket_suffix" {
  byte_length = 4
}

# В AWS Academy створення бакета через aws_s3_bucket викликає 403 через GetObjectLockConfiguration
# Тому створюємо бакет безпосередньо через AWS CLI у null_resource або використовуємо чистий S3 бакет
# Але найчистіший спосіб у Terraform для AWS Academy:
# Використати aws_s3_bucket без зайвих викликів або створити його через локальний виклик aws s3 mb
locals {
  bucket_name = "lab6-receipts-${random_id.bucket_suffix.hex}"
}

resource "null_resource" "create_s3_bucket" {
  triggers = {
    bucket_name = local.bucket_name
  }

  provisioner "local-exec" {
    command = "aws s3 mb s3://${local.bucket_name} --region ${var.aws_region}"
  }

  provisioner "local-exec" {
    when    = destroy
    command = "aws s3 rb s3://${self.triggers.bucket_name} --force"
  }
}
