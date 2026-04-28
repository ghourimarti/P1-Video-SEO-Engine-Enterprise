output "endpoint"         { value = aws_db_instance.postgres.endpoint }
output "port"             { value = aws_db_instance.postgres.port }
output "db_name"          { value = aws_db_instance.postgres.db_name }
output "secret_arn"       { value = aws_secretsmanager_secret.db_password.arn }
output "replica_endpoint" {
  value = length(aws_db_instance.replica) > 0 ? aws_db_instance.replica[0].endpoint : null
}
