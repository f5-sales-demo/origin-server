terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

module "juice_shop" {
  source = "../.."

  name            = "juice-demo"
  vpc_id          = "vpc-0123456789abcdef0"
  alb_subnet_ids  = ["subnet-0123456789abcdef0", "subnet-0123456789abcdef1"]
  task_subnet_ids = ["subnet-0123456789abcdef2", "subnet-0123456789abcdef3"]

  public_exposure             = true
  allowed_ingress_cidrs       = ["198.51.100.0/24"]
  cloudwatch_logs_kms_key_arn = var.cloudwatch_logs_kms_key_arn
  alb_access_logs_bucket      = var.alb_access_logs_bucket
}
