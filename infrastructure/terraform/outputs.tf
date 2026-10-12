output "app_public_ip" {
  value = aws_instance.app.public_ip
}
output "db_endpoint" {
  value = aws_db_instance.pg.address
}
output "s3_bucket" {
  value = aws_s3_bucket.data.bucket
}
output "db_secret_arn" {
  value = aws_db_instance.pg.master_user_secret[0].secret_arn
}
