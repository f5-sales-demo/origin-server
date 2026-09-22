variable "aws_region" {
  description = "AWS region containing the caller-managed VPC and subnets."
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Optional shared AWS configuration profile. Leave null to use standard ambient AWS authentication."
  type        = string
  default     = null
  nullable    = true
}

variable "cloudwatch_logs_kms_key_arn" {
  description = "ARN of the caller-managed KMS key for CloudWatch Logs encryption."
  type        = string
}

variable "alb_access_logs_bucket" {
  description = "Name of the caller-managed S3 bucket for ALB access logs."
  type        = string
}
