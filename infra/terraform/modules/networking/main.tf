# ── VPC + Subnets + NAT + Security Groups ─────────────────────────────────────

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs            = slice(data.aws_availability_zones.available.names, 0, 3)
  private_cidrs  = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  public_cidrs   = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 4, i + 4)]
  database_cidrs = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 4, i + 8)]
}

# ── VPC ────────────────────────────────────────────────────────────────────────
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.project}-${var.env}-vpc" }
}

# ── Internet Gateway ──────────────────────────────────────────────────────────
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-${var.env}-igw" }
}

# ── Public subnets (ELB, NAT GW, bastion) ────────────────────────────────────
resource "aws_subnet" "public" {
  count                   = length(local.azs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = local.public_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name                                              = "${var.project}-${var.env}-public-${local.azs[count.index]}"
    "kubernetes.io/role/elb"                          = "1"
    "kubernetes.io/cluster/${var.project}-${var.env}" = "shared"
  }
}

# ── Private subnets (EKS nodes, app workloads) ────────────────────────────────
resource "aws_subnet" "private" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = {
    Name                                              = "${var.project}-${var.env}-private-${local.azs[count.index]}"
    "kubernetes.io/role/internal-elb"                 = "1"
    "kubernetes.io/cluster/${var.project}-${var.env}" = "shared"
    "karpenter.sh/discovery"                          = "${var.project}-${var.env}"
  }
}

# ── Database subnets (RDS, ElastiCache — no route to internet) ───────────────
resource "aws_subnet" "database" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.database_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = { Name = "${var.project}-${var.env}-db-${local.azs[count.index]}" }
}

resource "aws_db_subnet_group" "main" {
  name       = "${var.project}-${var.env}-db"
  subnet_ids = aws_subnet.database[*].id
  tags       = { Name = "${var.project}-${var.env}-db-subnet-group" }
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.project}-${var.env}-redis"
  subnet_ids = aws_subnet.database[*].id
}

# ── NAT Gateway (one per AZ for HA) ──────────────────────────────────────────
resource "aws_eip" "nat" {
  count  = var.single_nat_gateway ? 1 : length(local.azs)
  domain = "vpc"
  tags   = { Name = "${var.project}-${var.env}-nat-eip-${count.index}" }
}

resource "aws_nat_gateway" "main" {
  count         = var.single_nat_gateway ? 1 : length(local.azs)
  subnet_id     = aws_subnet.public[count.index].id
  allocation_id = aws_eip.nat[count.index].id
  tags          = { Name = "${var.project}-${var.env}-nat-${count.index}" }
  depends_on    = [aws_internet_gateway.main]
}

# ── Route tables ──────────────────────────────────────────────────────────────
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "${var.project}-${var.env}-public-rt" }
}

resource "aws_route_table_association" "public" {
  count          = length(local.azs)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count  = var.single_nat_gateway ? 1 : length(local.azs)
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[var.single_nat_gateway ? 0 : count.index].id
  }
  tags = { Name = "${var.project}-${var.env}-private-rt-${count.index}" }
}

resource "aws_route_table_association" "private" {
  count          = length(local.azs)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[var.single_nat_gateway ? 0 : count.index].id
}

# ── Security Groups ───────────────────────────────────────────────────────────
resource "aws_security_group" "api" {
  name        = "${var.project}-${var.env}-api-sg"
  description = "FastAPI pods"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    description = "API port from within VPC"
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${var.project}-${var.env}-api-sg" }
}

resource "aws_security_group" "rds" {
  name        = "${var.project}-${var.env}-rds-sg"
  description = "RDS Postgres"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
    description     = "Postgres from API pods"
  }
  tags = { Name = "${var.project}-${var.env}-rds-sg" }
}

resource "aws_security_group" "redis" {
  name        = "${var.project}-${var.env}-redis-sg"
  description = "ElastiCache Redis"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
    description     = "Redis from API pods"
  }
  tags = { Name = "${var.project}-${var.env}-redis-sg" }
}
