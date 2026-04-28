# ── ElastiCache Redis 7 (cluster mode disabled, multi-AZ with replica) ────────

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = "${var.project}-${var.env}-redis"
  description          = "Semantic cache + rate limiting for ${var.project} ${var.env}"

  node_type            = var.node_type
  num_cache_clusters   = var.env == "prod" ? 2 : 1   # primary + 1 replica in prod
  port                 = 6379
  parameter_group_name = aws_elasticache_parameter_group.redis7.name
  subnet_group_name    = var.redis_subnet_group_name
  security_group_ids   = [var.redis_sg_id]

  engine_version    = "7.1"
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true

  # Multi-AZ automatic failover (prod only)
  automatic_failover_enabled = var.env == "prod"
  multi_az_enabled           = var.env == "prod"

  # Snapshots
  snapshot_retention_limit = var.env == "prod" ? 5 : 1
  snapshot_window          = "04:00-05:00"
  maintenance_window       = "mon:05:00-mon:06:00"

  # Slow log to CloudWatch
  log_delivery_configuration {
    destination      = aws_cloudwatch_log_group.redis_slow.name
    destination_type = "cloudwatch-logs"
    log_format       = "json"
    log_type         = "slow-log"
  }

  tags = { Name = "${var.project}-${var.env}-redis" }
}

resource "aws_elasticache_parameter_group" "redis7" {
  name   = "${var.project}-${var.env}-redis7"
  family = "redis7"

  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"   # evict LRU keys when memory full
  }

  parameter {
    name  = "slowlog-log-slower-than"
    value = "10000"   # 10 ms
  }
}

resource "aws_cloudwatch_log_group" "redis_slow" {
  name              = "/aws/elasticache/${var.project}-${var.env}/slow-log"
  retention_in_days = 14
}
