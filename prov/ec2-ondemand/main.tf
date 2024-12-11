variable "deployment_name" {}
variable "public_key_path" {}
variable "owner" {}
variable "access_key" {}
variable "secret_key" {}
variable "region" {}
variable "availability_zone" {}
variable "server_count" { type = number }
variable "server_instance_type" {}
variable "server_ami" {}
variable "monitor_instance_type" {}
variable "monitor_ami" {}
variable "client_instance_type" {}
variable "client_count" { type = number }
variable "client_ami" {}

resource "random_id" "deployment_salt" {
  byte_length = 8
}
locals {
  deployment_id = "${var.deployment_name}-${random_id.deployment_salt.hex}"
}

provider "aws" {
  access_key = var.access_key
  secret_key = var.secret_key
  region     = var.region
}

resource "aws_key_pair" "main" {
  key_name   = "sso-keypair-${local.deployment_id}"
  public_key = file(var.public_key_path)
  tags = {
    Name       = "sso-keypair-${local.deployment_id}"
    Deployment = "${local.deployment_id}"
    Owner      = var.owner
  }
}

resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
  tags = {
    Name       = "sso-vpc-${local.deployment_id}"
    Deployment = "${local.deployment_id}"
    Owner      = var.owner
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags = {
    Name       = "sso-igw-${local.deployment_id}"
    Deployment = "${local.deployment_id}"
    Owner      = var.owner
  }
}

resource "aws_route" "main" {
  route_table_id         = aws_vpc.main.default_route_table_id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_subnet" "main" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = true
  tags = {
    Name       = "sso-subnet-${local.deployment_id}"
    Deployment = "${local.deployment_id}"
    Owner      = var.owner
  }
}

# ========== servers ==========================

resource "aws_security_group" "server" {
  name        = "sso-server-sg-${local.deployment_id}"
  description = "Security group for Scylla servers"
  vpc_id      = aws_vpc.main.id

  # list of ports https://docs.scylladb.com/operating-scylla/admin/

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "CQL"
    from_port   = 9042
    to_port     = 9042
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSL_CQL"
    from_port   = 9142
    to_port     = 9142
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "RPC"
    from_port   = 7000
    to_port     = 7000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSL RPC"
    from_port   = 7001
    to_port     = 7001
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "JMX"
    from_port   = 7199
    to_port     = 7199
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "REST"
    from_port   = 10000
    to_port     = 10000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "NodeExporter"
    from_port   = 9100
    to_port     = 9100
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Prometheus"
    from_port   = 9180
    to_port     = 9180
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Thrift"
    from_port   = 9160
    to_port     = 9160
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name       = "sso-server-sg-${local.deployment_id}"
    Deployment = "${local.deployment_id}"
    Owner      = var.owner
  }

  lifecycle {
    create_before_destroy = true
  }
}

#resource "aws_spot_instance_request" "server" {
#  key_name             = aws_key_pair.main.key_name
#  ami                  = var.server_ami
#  instance_type        = var.server_instance_type
#  count                = var.server_count
#  availability_zone    = var.availability_zone
#  subnet_id            = aws_subnet.main.id
#  wait_for_fulfillment = true
#  spot_type            = "one-time"
#
#  tags = {
#    Name       = "sso-server-spot-request-${count.index}-${local.deployment_id}",
#    keep       = "alive"
#    Deployment = "${local.deployment_id}"
#    Owner      = var.owner
#  }
#
#  vpc_security_group_ids = [
#    aws_security_group.server.id
#  ]
#
#  ebs_block_device {
#    device_name = "/dev/sda1"
#    volume_type = "gp3"
#    volume_size = 100
#  }
#
#  # Terraform reprovisions the scylla node even when its configuration hasn't changed. This workaround prevents that.
#  lifecycle {
#    ignore_changes = [ebs_block_device]
#  }
#
#  user_data = jsonencode({
#    start_scylla_on_first_boot = false
#  })
#}
#
#resource "aws_ec2_tag" "server-name" {
#  for_each    = { for i, v in aws_spot_instance_request.server : i => v }
#  resource_id = each.value.spot_instance_id
#  key         = "Name"
#  value       = "sso-server-spot-instance-${each.key}-${local.deployment_id}"
#}
#resource "aws_ec2_tag" "server-alive" {
#  for_each    = { for i, v in aws_spot_instance_request.server : i => v }
#  resource_id = each.value.spot_instance_id
#  key         = "keep"
#  value       = "alive"
#}
#resource "aws_ec2_tag" "server-deployment" {
#  for_each    = { for i, v in aws_spot_instance_request.server : i => v }
#  resource_id = each.value.spot_instance_id
#  key         = "Deployment"
#  value       = local.deployment_id
#}
#resource "aws_ec2_tag" "server-owner" {
#  for_each    = { for i, v in aws_spot_instance_request.server : i => v }
#  resource_id = each.value.spot_instance_id
#  key         = "Owner"
#  value       = var.owner
#}

resource "aws_instance" "server" {
  key_name          = aws_key_pair.main.key_name
  ami               = var.server_ami
  instance_type     = var.server_instance_type
  count             = var.server_count
  availability_zone = var.availability_zone
  subnet_id         = aws_subnet.main.id

  tags = {
    Name       = "sso-server-${count.index}-${local.deployment_id}"
    Deployment = "${local.deployment_id}"
    Owner      = var.owner
    keep       = "alive"
  }

  vpc_security_group_ids = [
    aws_security_group.server.id
  ]

  ebs_block_device {
    device_name = "/dev/sda1"
    volume_type = "gp3"
    volume_size = 100
  }

  # Terraform reprovisions the scylla node even when its configuration hasn't changed. This workaround prevents that.
  lifecycle {
    ignore_changes = [ebs_block_device]
  }

  user_data = jsonencode({
    start_scylla_on_first_boot = false
  })
}

# ========== monitor ==========================

resource "aws_security_group" "monitor" {
  name        = "sso-monitor-sg-${local.deployment_id}"
  description = "Security group for Prometheus"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Prometheus"
    from_port   = 9090
    to_port     = 9090
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Grafana"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Alert Manager"
    from_port   = 9003
    to_port     = 9003
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name       = "sso-monitor-sg-${local.deployment_id}"
    Deployment = "${local.deployment_id}"
    Owner      = var.owner
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_instance" "monitor" {
  key_name          = aws_key_pair.main.key_name
  ami               = var.monitor_ami
  instance_type     = var.monitor_instance_type
  availability_zone = var.availability_zone
  subnet_id         = aws_subnet.main.id
  count             = 1

  tags = {
    Name       = "sso-monitor-${count.index}-${local.deployment_id}"
    Deployment = "${local.deployment_id}"
    Owner      = var.owner
    keep       = "alive"
  }

  vpc_security_group_ids = [
    aws_security_group.monitor.id
  ]

  lifecycle {
    ignore_changes = [ebs_block_device]
  }

  ebs_block_device {
    device_name = "/dev/sda1"
    volume_type = "gp3"
    volume_size = 384
  }
}

# ========== clients ==========================

resource "aws_security_group" "client" {
  name        = "sso-client-sg-${local.deployment_id}"
  description = "Security group for Scylla clients"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "cassandra-stress-daemon"
    from_port   = 2159
    to_port     = 2159
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "terraform",
    keep = "alive"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_spot_instance_request" "client" {
  key_name             = aws_key_pair.main.key_name
  ami                  = var.client_ami
  instance_type        = var.client_instance_type
  count                = var.client_count
  availability_zone    = var.availability_zone
  subnet_id            = aws_subnet.main.id
  wait_for_fulfillment = true
  spot_type            = "one-time"

  tags = {
    Name       = "sso-client-spot-request-${count.index}-${local.deployment_id}",
    keep       = "alive"
    Deployment = "${local.deployment_id}"
    Owner      = var.owner
  }

  vpc_security_group_ids = [
    aws_security_group.client.id
  ]
}

resource "aws_ec2_tag" "client-name" {
  for_each    = { for i, v in aws_spot_instance_request.client : i => v }
  resource_id = each.value.spot_instance_id
  key         = "Name"
  value       = "sso-client-spot-instance-${each.key}-${local.deployment_id}"
}
resource "aws_ec2_tag" "client-alive" {
  for_each    = { for i, v in aws_spot_instance_request.client : i => v }
  resource_id = each.value.spot_instance_id
  key         = "keep"
  value       = "alive"
}
resource "aws_ec2_tag" "client-deployment" {
  for_each    = { for i, v in aws_spot_instance_request.client : i => v }
  resource_id = each.value.spot_instance_id
  key         = "Deployment"
  value       = local.deployment_id
}
resource "aws_ec2_tag" "client-owner" {
  for_each    = { for i, v in aws_spot_instance_request.client : i => v }
  resource_id = each.value.spot_instance_id
  key         = "Owner"
  value       = var.owner
}
