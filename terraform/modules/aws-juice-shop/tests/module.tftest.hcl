mock_provider "aws" {}

variables {
  name                        = "juice-demo"
  vpc_id                      = "vpc-0123456789abcdef0"
  alb_subnet_ids              = ["subnet-0123456789abcdef0", "subnet-0123456789abcdef1"]
  task_subnet_ids             = ["subnet-0123456789abcdef2", "subnet-0123456789abcdef3"]
  allowed_ingress_cidrs       = ["10.0.0.0/8"]
  cloudwatch_logs_kms_key_arn = "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
  alb_access_logs_bucket      = "example-alb-logs"
}

override_data {
  target = data.aws_subnet.alb["0"]
  values = {
    vpc_id            = "vpc-0123456789abcdef0"
    availability_zone = "us-east-1a"
  }
}

override_data {
  target = data.aws_subnet.alb["1"]
  values = {
    vpc_id            = "vpc-0123456789abcdef0"
    availability_zone = "us-east-1b"
  }
}

override_data {
  target = data.aws_subnet.task["0"]
  values = {
    vpc_id = "vpc-0123456789abcdef0"
  }
}

override_data {
  target = data.aws_subnet.task["1"]
  values = {
    vpc_id = "vpc-0123456789abcdef0"
  }
}

run "private_least_privilege_contract" {
  command = plan

  override_data {
    target = data.aws_subnet.alb["0"]
    values = {
      vpc_id            = "vpc-0123456789abcdef0"
      availability_zone = "us-east-1a"
    }
  }

  override_data {
    target = data.aws_subnet.alb["1"]
    values = {
      vpc_id            = "vpc-0123456789abcdef0"
      availability_zone = "us-east-1b"
    }
  }

  override_resource {
    target          = aws_security_group.alb
    values          = { id = "sg-0123456789abcdef0" }
    override_during = plan
  }

  override_resource {
    target          = aws_cloudwatch_log_group.this
    values          = { arn = "arn:aws:logs:us-east-1:123456789012:log-group:/ecs/juice-demo" }
    override_during = plan
  }

  assert {
    condition     = aws_lb.this.internal && aws_lb.this.load_balancer_type == "application"
    error_message = "The default origin must use an internal Application Load Balancer."
  }

  assert {
    condition     = aws_cloudwatch_log_group.this.retention_in_days >= 365 && aws_cloudwatch_log_group.this.kms_key_id == var.cloudwatch_logs_kms_key_arn
    error_message = "CloudWatch logs must retain data for at least one year and use the caller-provided KMS key."
  }

  assert {
    condition     = contains([for setting in aws_ecs_cluster.this.setting : "${setting.name}:${setting.value}"], "containerInsights:enabled")
    error_message = "The ECS cluster must enable Container Insights."
  }

  assert {
    condition     = aws_lb.this.drop_invalid_header_fields && aws_lb.this.access_logs[0].enabled && aws_lb.this.access_logs[0].bucket == var.alb_access_logs_bucket
    error_message = "The ALB must drop invalid headers and publish access logs to the caller-provided bucket."
  }

  assert {
    condition     = aws_lb.this.subnets == toset(var.alb_subnet_ids)
    error_message = "The ALB must use only alb_subnet_ids."
  }

  assert {
    condition     = aws_ecs_service.this.network_configuration[0].subnets == toset(var.task_subnet_ids) && !aws_ecs_service.this.network_configuration[0].assign_public_ip
    error_message = "Fargate tasks must use task_subnet_ids without public IP addresses."
  }

  assert {
    condition     = aws_vpc_security_group_ingress_rule.task.referenced_security_group_id == "sg-0123456789abcdef0" && aws_vpc_security_group_ingress_rule.task.from_port == var.container_port && aws_vpc_security_group_ingress_rule.task.to_port == var.container_port
    error_message = "Task ingress must allow only the ALB security group on the container port."
  }

  assert {
    condition     = alltrue([for rule in values(aws_vpc_security_group_ingress_rule.alb) : rule.from_port != 22 && rule.to_port != 22]) && aws_vpc_security_group_ingress_rule.task.from_port != 22
    error_message = "The module must not create SSH ingress."
  }

  assert {
    condition     = aws_iam_role_policy.task_execution.policy == jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.this.arn}:*" }] })
    error_message = "Execution IAM permissions must be limited to writing this module's log streams."
  }

  assert {
    condition     = aws_ecs_service.this.deployment_circuit_breaker[0].enable && aws_ecs_service.this.deployment_circuit_breaker[0].rollback
    error_message = "ECS deployments must enable the circuit breaker and automatic rollback."
  }
}

run "public_exposure_is_explicit" {
  command = plan

  variables {
    public_exposure       = true
    allowed_ingress_cidrs = ["198.51.100.0/24"]
  }

  override_data {
    target = data.aws_subnet.alb["0"]
    values = { vpc_id = "vpc-0123456789abcdef0", availability_zone = "us-east-1a" }
  }

  override_data {
    target = data.aws_subnet.alb["1"]
    values = { vpc_id = "vpc-0123456789abcdef0", availability_zone = "us-east-1b" }
  }

  assert {
    condition     = !aws_lb.this.internal
    error_message = "public_exposure=true must create an internet-facing ALB."
  }
}

run "reject_world_open_private_alb" {
  command = plan
  variables { allowed_ingress_cidrs = ["0.0.0.0/0"] }
  expect_failures = [var.allowed_ingress_cidrs]
}

run "allow_world_open_only_when_public" {
  command = plan
  variables {
    public_exposure       = true
    allowed_ingress_cidrs = ["0.0.0.0/0"]
  }

  override_data {
    target = data.aws_subnet.alb["0"]
    values = { vpc_id = "vpc-0123456789abcdef0", availability_zone = "us-east-1a" }
  }
  override_data {
    target = data.aws_subnet.alb["1"]
    values = { vpc_id = "vpc-0123456789abcdef0", availability_zone = "us-east-1b" }
  }
}

run "reject_alb_subnets_in_different_vpc" {
  command = plan
  override_data {
    target = data.aws_subnet.alb["0"]
    values = { vpc_id = "vpc-0123456789abcdef0", availability_zone = "us-east-1a" }
  }
  override_data {
    target = data.aws_subnet.alb["1"]
    values = { vpc_id = "vpc-fedcba98765432100", availability_zone = "us-east-1b" }
  }
  expect_failures = [check.alb_subnet_placement]
}

run "reject_alb_subnets_in_one_az" {
  command = plan
  override_data {
    target = data.aws_subnet.alb["0"]
    values = { vpc_id = "vpc-0123456789abcdef0", availability_zone = "us-east-1a" }
  }
  override_data {
    target = data.aws_subnet.alb["1"]
    values = { vpc_id = "vpc-0123456789abcdef0", availability_zone = "us-east-1a" }
  }
  expect_failures = [check.alb_subnet_placement]
}

run "reject_task_subnet_in_different_vpc" {
  command = plan

  override_data {
    target = data.aws_subnet.task["1"]
    values = { vpc_id = "vpc-fedcba98765432100" }
  }

  expect_failures = [check.task_subnet_placement]
}

run "reject_unpinned_image" {
  command = plan
  variables { container_image = "bkimminich/juice-shop:latest" }
  expect_failures = [var.container_image]
}

run "reject_single_alb_subnet" {
  command = plan
  variables { alb_subnet_ids = ["subnet-0123456789abcdef0"] }
  expect_failures = [var.alb_subnet_ids]
}

run "reject_empty_task_subnets" {
  command = plan
  variables { task_subnet_ids = [] }
  expect_failures = [var.task_subnet_ids]
}

run "reject_empty_ingress" {
  command = plan
  variables { allowed_ingress_cidrs = [] }
  expect_failures = [var.allowed_ingress_cidrs]
}

run "reject_invalid_name" {
  command = plan
  variables { name = "Invalid_Name" }
  expect_failures = [var.name]
}

run "reject_invalid_fargate_size" {
  command = plan
  variables {
    cpu    = 256
    memory = 4096
  }
  expect_failures = [var.memory]
}
