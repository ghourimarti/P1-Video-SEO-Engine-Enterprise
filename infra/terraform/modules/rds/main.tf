# ── RDS Postgres 16 + pgvector parameter group ────────────────────────────────

resource "random_password" "db" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "db_password" {
  name                    = "${var.project}/${var.env}/api/db_password"
  recovery_window_in_days = var.env == "prod" ? 7 : 0
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = random_password.db.result
}

# ── Parameter group: enable pgvector ─────────────────────────────────────────
resource "aws_db_parameter_group" "postgres16_pgvector" {
  name   = "${var.project}-${var.env}-pg16-pgvector"
  family = "postgres16"

  parameter {
    name  = "shared_preload_libraries"
    value = "pgvector"
  }

  parameter {
    name  = "max_connections"
    value = var.max_connections
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"   # log queries > 1s
  }
}

# ── Subnet group ──────────────────────────────────────────────────────────────
# (reuse the one created in networking module)

# ── RDS instance ──────────────────────────────────────────────────────────────
resource "aws_db_instance" "postgres" {
  identifier        = "${var.project}-${var.env}-postgres"
  engine            = "postgres"
  engine_version    = "16.3"
  instance_class    = var.instance_class
  allocated_storage = var.allocated_storage_gb
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db.result

  db_subnet_group_name   = var.db_subnet_group_name
  vpc_security_group_ids = [var.rds_sg_id]
  parameter_group_name   = aws_db_parameter_group.postgres16_pgvector.name

  # Backups
  backup_retention_period = var.env == "prod" ? 14 : 1
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  # High availability
  multi_az = var.env == "prod"

  # Deletion protection — always on in prod
  deletion_protection = var.env == "prod"

  # Final snapshot only in prod
  skip_final_snapshot       = var.env != "prod"
  final_snapshot_identifier = var.env == "prod" ? "${var.project}-${var.env}-final" : null

  # Performance Insights
  performance_insights_enabled = true

  tags = { Name = "${var.project}-${var.env}-postgres" }
}

# ── Read replica (prod only) ──────────────────────────────────────────────────
resource "aws_db_instance" "replica" {
  count               = var.env == "prod" ? 1 : 0
  identifier          = "${var.project}-${var.env}-postgres-replica"
  replicate_source_db = aws_db_instance.postgres.identifier
  instance_class      = var.instance_class
  storage_encrypted   = true

  # Replica uses same security group
  vpc_security_group_ids = [var.rds_sg_id]

  skip_final_snapshot = true
  tags                = { Name = "${var.project}-${var.env}-postgres-replica" }
}
