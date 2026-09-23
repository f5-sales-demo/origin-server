# AWS Juice Shop origin module

Deploys the intentionally vulnerable OWASP Juice Shop container on private AWS Fargate tasks behind an Application Load Balancer (ALB). Use only in authorized demo infrastructure.

## Architecture and authorization

The caller owns the VPC, ALB subnets, private task subnets, routing, provider authentication,
CloudWatch Logs KMS key, and ALB access-log S3 bucket. The module creates an ALB/listener/target
group, ECS cluster/service/task definition, security groups, an execution role with log-only
permissions, and a KMS-encrypted CloudWatch log group retained for at least 365 days. It creates no
SSH access, credentials, VPC, NAT gateway, KMS key, S3 bucket, or Terraform state backend.

`public_exposure` defaults to `false`, producing an internal ALB. Internet-facing exposure requires
`public_exposure = true`. Even then, restrict `allowed_ingress_cidrs` to approved source networks.
`0.0.0.0/0` is accepted only with explicit public exposure and is not recommended.

## Trust boundary

F5 Distributed Cloud is the public HTTPS termination and security enforcement point for this
origin design. Client-Side Defense and other configured edge controls run there; the module does
not create an AWS WAF because that would duplicate the enforcement point and expand the reusable
origin module's responsibility.

Traffic from F5 Distributed Cloud to the ALB intentionally uses HTTP. The ALB security group limits
port 80 ingress to `allowed_ingress_cidrs`, which operators must set to the approved F5 Distributed
Cloud egress or connected-network CIDRs. This hop is not encrypted, so its routing domain must be
trusted and protected from interception; use a different origin design if that trust cannot be
established.

The Juice Shop target natively serves HTTP. Fargate tasks have no public IP address and run in
caller-managed private subnets. Their security group accepts the container port only from the ALB
security group, so neither F5 Distributed Cloud nor arbitrary VPC sources connect directly to a
task. These controls are part of the exception rationale and must not be relaxed.

Deletion protection is intentionally disabled: this is ephemeral authorized demo infrastructure and must support prompt Terraform teardown after use.

## Prerequisites and routing

- Terraform >= 1.7 and AWS provider 6.x.
- Caller authorization to create ALB, ECS, IAM role/policy, CloudWatch Logs, and security-group resources. The applying principal also needs `iam:PassRole` narrowly scoped to the module-created ECS task execution role and constrained to `iam:PassedToService = ecs-tasks.amazonaws.com`.
- Two or more ALB subnets in `vpc_id`, spanning at least two Availability Zones. The module validates this with `aws_subnet` data.
- One or more caller-managed private task subnets in `vpc_id` are accepted for any `desired_count`. Multiple task subnets across Availability Zones are recommended for resilience, not required by the module.
- Task-subnet egress through NAT or an approved proxy for the Docker Hub image, plus AWS Logs connectivity; equivalent private endpoints and egress controls are acceptable. The module does not claim that private tasks can pull the image without this connectivity.
- For an internal ALB, its private addresses must be reachable from the F5 Distributed Cloud origin path through implemented private connectivity and bidirectional routing. For an internet-facing ALB, every ALB subnet must have a default route to an internet gateway. The module validates VPC and Availability Zone placement, not route-table semantics.
- A caller-managed symmetric KMS key. Its key policy must allow the regional CloudWatch Logs service principal (`logs.<region>.amazonaws.com`) to perform `kms:Encrypt`, `kms:Decrypt`, `kms:ReEncrypt*`, `kms:GenerateDataKey*`, and `kms:Describe*`. Constrain access with `kms:ViaService`, the source account, and the log-group ARN in the encryption context.
- A caller-managed S3 bucket in the same Region as the ALB, using SSE-S3 rather than SSE-KMS for ALB access logs. The caller owns retention/lifecycle, public-access blocking, and the regional Elastic Load Balancing log-delivery bucket policy.

## Immutable consumption

No release tag is currently proven to contain both this module and computed-subnet support.
Release `v1.7.88` predates the AWS module and must not be cited as containing it. Until a
later release is verified, consumers must pin the canonical provenance commit
`d6384bb0621c4c1eceb38d55a6b63e7b9cc7083a`:

```hcl
module "juice_shop" {
  source = "git::https://github.com/f5-sales-demo/origin-server.git//terraform/modules/aws-juice-shop?ref=d6384bb0621c4c1eceb38d55a6b63e7b9cc7083a"

  # inputs omitted
}
```

The local example uses `source = "../.."` only so repository validation does not require network
access. The CSD reference implementation consumes a vendored copy of this module and records this
same upstream repository path and commit as its provenance. A vendored copy is independently owned
by its consuming repository: compare it with the pinned upstream commit before upgrading, and do
not assume later upstream changes are present.

## Computed subnet IDs

`alb_subnet_ids` and `task_subnet_ids` may contain IDs produced by subnet resources in the same
configuration. The ID values may therefore be unknown during planning. The number of list elements
must still be known during planning because the module derives stable `for_each` keys from list
indices for its subnet data sources. Conditional expressions that make the list length unknown until
apply are not supported.

Supply at least two distinct ALB subnet elements whose resolved subnets belong to `vpc_id` and span
at least two Availability Zones. Supply at least one task subnet element; every resolved task subnet
must belong to `vpc_id`. The module checks resolved VPC and Availability Zone placement during apply
when those attributes were not available during planning. A failed check can therefore occur after
some resources have been created; use the state-aware recovery procedure below rather than deleting
resources manually.

```hcl
module "juice_shop" {
  source = "git::https://github.com/f5-sales-demo/origin-server.git//terraform/modules/aws-juice-shop?ref=d6384bb0621c4c1eceb38d55a6b63e7b9cc7083a"

  name            = "juice-demo"
  vpc_id          = aws_vpc.demo.id
  alb_subnet_ids  = [aws_subnet.alb_a.id, aws_subnet.alb_b.id]
  task_subnet_ids = [aws_subnet.task_a.id]

  cloudwatch_logs_kms_key_arn = aws_kms_key.logs.arn
  alb_access_logs_bucket      = aws_s3_bucket.alb_logs.bucket
}
```

The fixed list expressions above have plan-known cardinality even though their values are computed.
The caller still owns the VPC, subnet resources, routes, KMS key and policy, S3 bucket and policy,
AWS provider authentication, Terraform backend, and state.

## Inputs

| Name | Type | Required | Default | Constraint and behavior |
| --- | --- | --- | --- | --- |
| `name` | `string` | yes | — | 2–32 characters; starts with a lowercase letter, ends with a lowercase letter or digit, and contains only lowercase letters, digits, and hyphens. |
| `vpc_id` | `string` | yes | — | Must match an AWS VPC ID (`vpc-` followed by lowercase hexadecimal characters). The VPC is caller-managed. |
| `alb_subnet_ids` | `list(string)` | yes | — | At least two distinct AWS subnet IDs. Resolved subnets must belong to `vpc_id` and span at least two Availability Zones; list cardinality must be known at plan time. |
| `task_subnet_ids` | `list(string)` | yes | — | At least one AWS subnet ID for any `desired_count`. Resolved subnets must belong to `vpc_id`; list cardinality must be known at plan time. Tasks receive no public IP. Multiple Availability Zones are recommended for resilience, not required. |
| `public_exposure` | `bool` | no | `false` | `false` creates an internal ALB whose private addresses require implemented private F5 Distributed Cloud connectivity and routing; `true` creates an internet-facing ALB whose subnets require internet-gateway routes. Route-table semantics are caller-owned and not module-validated. |
| `allowed_ingress_cidrs` | `set(string)` | no | RFC 1918 IPv4 ranges | Non-empty set of valid IPv4 CIDRs. `0.0.0.0/0` is rejected unless `public_exposure = true`; broad ingress is not recommended. |
| `container_image` | `string` | no | Digest-pinned Juice Shop image | Must end in `@sha256:` followed by exactly 64 lowercase hexadecimal characters. Mutable tags are rejected. |
| `container_port` | `number` | no | `3000` | Integer TCP port from 1024 through 65535. |
| `desired_count` | `number` | no | `1` | Positive integer Fargate task count. |
| `cpu` | `number` | no | `512` | One of `256`, `512`, `1024`, `2048`, `4096`, `8192`, or `16384`. |
| `memory` | `number` | no | `1024` | MiB value valid for the selected Fargate CPU according to the validation matrix in `variables.tf`. |
| `cloudwatch_log_retention_days` | `number` | no | `365` | Must be at least 365 days. |
| `cloudwatch_logs_kms_key_arn` | `string` | yes | — | Valid AWS, AWS GovCloud, or AWS China symmetric KMS key ARN with a UUID key ID. The key policy must grant the regional CloudWatch Logs principal the documented encrypt, decrypt, re-encrypt, data-key, and describe actions, scoped by service, source account, and log-group encryption context. |
| `alb_access_logs_bucket` | `string` | yes | — | Caller-managed S3 bucket in the ALB Region, 3–63 characters, using SSE-S3 and the required regional ALB log-delivery policy; SSE-KMS is unsupported for ALB access logs. |
| `alb_access_logs_prefix` | `string` | no | `juice-shop` | Must not start or end with `/` and must not contain `AWSLogs`. |
| `tags` | `map(string)` | no | `{}` | Additional tags merged with the module's `Name` tag on supported resources. |

The AWS provider is `hashicorp/aws >= 6.0, < 7.0`; Terraform must be version 1.7.0 or later.
The module does not configure a provider, authenticate to AWS, or create a backend.

## Outputs

| Name | Description |
| --- | --- |
| `origin_hostname` | ALB DNS hostname for the origin. |
| `origin_url` | HTTP URL formed from the ALB hostname. |
| `listener_port` | ALB HTTP listener port. |
| `listener_protocol` | ALB listener protocol. |
| `ecs_cluster_id` | ECS cluster identifier. |
| `ecs_service_id` | ECS service identifier. |
| `task_definition_arn` | ECS task definition ARN. |
| `load_balancer_arn` | Application Load Balancer ARN. |
| `target_group_arn` | ALB target group ARN. |
| `alb_security_group_id` | Security group protecting the ALB. |
| `task_security_group_id` | Security group protecting the Fargate tasks. |
| `vpc_id` | Caller-provided VPC ID. |
| `alb_subnet_ids` | Caller-provided ALB subnet ID list, including computed values after apply. |
| `task_subnet_ids` | Caller-provided Fargate task subnet ID list, including computed values after apply. |
| `container_image` | Immutable image reference used by the task definition. |

`origin_hostname` and `origin_url` may be reachable only from connected networks when the ALB is
internal. Output values describe module resources or echo caller inputs; they do not transfer
ownership of caller-managed infrastructure to the module.

## Validate, deploy, and verify

Initialize and validate the standalone module before consuming it. The test suite contains 13 plan
contracts covering the private least-privilege baseline, explicit public exposure, subnet placement,
immutable images, required collection sizes, ingress, naming, and Fargate sizing:

```bash
terraform init -backend=false
terraform validate
terraform test
```

A successful test run reports `Success! 13 passed, 0 failed.` These mocked plan tests validate the
Terraform contract; they do not prove live routing, image access, log delivery, or workload health.

Expose the module URL from the caller root before using `terraform output`:

```hcl
output "origin_url" {
  description = "HTTP URL of the Juice Shop origin."
  value       = module.juice_shop.origin_url
}
```

From the caller configuration, save and inspect a plan before applying it:

```bash
install -d -m 700 .artifacts
terraform init
terraform plan -out=.artifacts/tfplan
terraform show .artifacts/tfplan
terraform apply .artifacts/tfplan
terraform output origin_url
```

Saved plans can contain sensitive configuration and state-derived values. Keep `.artifacts/` private,
ignored, and out of logs or plan-JSON exports; remove saved plans when they are no longer needed.

After apply, verify all of the following with the caller's normal AWS and network observability tools:

1. The ECS service reaches steady state with the requested task count.
2. Every registered target in the module target group is healthy.
3. CloudWatch receives container log events and the log group uses the requested KMS key and retention.
4. ALB access-log objects arrive under the configured bucket and prefix.
5. An approved client can fetch Juice Shop through `origin_url`. For an internal ALB, test from the VPC, VPN, Direct Connect, or another authorized routed network; for an internet-facing ALB, test only from an allowed CIDR.
6. A client outside `allowed_ingress_cidrs` cannot reach the listener.
7. A new `terraform plan` reports no changes.

Do not interpret an unreachable internal hostname as a reason to enable public exposure. Fix the
caller-owned routing or test from an authorized connected network.

## Image and module upgrades

For an image upgrade, resolve and review a new Juice Shop digest, update `container_image`, run the
13-test contract, inspect a saved plan, and apply it. The ECS deployment circuit breaker automatically
rolls back a failed deployment. Never replace the digest with a mutable tag such as `latest`.

For a module upgrade, compare the currently pinned source or vendored copy with the candidate upstream
commit, review its Terraform and migration impact, update the immutable source reference and recorded
provenance together, run validation and all 13 tests, then plan before applying. Do not move to a
release tag until that tag is proven to contain the required module and computed-subnet behavior.

## Partial-apply recovery

Terraform may create resources before a provider error, failed placement check, missing caller-owned
dependency, or interrupted apply stops the operation. Preserve the working directory, backend, state,
provider lock file, and exact configuration. Do not delete resources in the AWS console and do not
remove objects from state merely to make the next plan smaller.

1. Read the complete Terraform error and AWS service event.
2. Correct the caller-owned prerequisite or input, such as subnet placement, routes, KMS policy, S3 bucket policy, quota, or task egress.
3. Run `terraform plan` with the same backend and state. Terraform will reconcile resources already recorded in state and propose only the remaining or corrective actions.
4. Inspect and apply the new saved plan, then perform every runtime verification above.
5. If an object exists in AWS but is absent from state, determine why before proceeding. Import it only when the configuration intentionally owns it; otherwise remove the orphan through the owning workflow after confirming it is safe.

If recovery cannot produce a coherent deployment, use a reviewed destroy plan against the same state
before retrying. Never start a second state for the same infrastructure.

## Costs

The module can incur ALB hourly and capacity-unit charges, Fargate compute charges, Container Insights
metrics charges, CloudWatch Logs storage and KMS request charges, S3 access-log storage, and data-transfer
charges. Caller-managed NAT gateways, proxies, private endpoints, KMS keys, S3 buckets, and their data
processing or storage can add costs but are not module resources. Review current regional AWS pricing
and expected traffic before deployment.

## Destroy

Destroy from the caller configuration with the same backend, workspace, state, provider identity, and
module source used for deployment:

```bash
install -d -m 700 .artifacts
terraform plan -destroy -out=.artifacts/destroy.tfplan
terraform show .artifacts/destroy.tfplan
terraform apply .artifacts/destroy.tfplan
```

Confirm that the plan targets only the intended module-owned ALB/listener/target group, ECS resources,
security groups, execution role and policy, and CloudWatch log group. After apply, confirm those
resources are gone and remove obsolete saved plans. The caller-owned VPC, subnets, routes, NAT gateway,
proxy, endpoints, KMS key, S3 bucket and logs, provider authentication, backend, and Terraform state
remain. Apply the caller's retention and cleanup policies to those resources separately.

## Troubleshooting

- **ALB subnet validation fails:** confirm every resolved ALB subnet belongs to `vpc_id`, the list contains at least two distinct elements, and the subnets span two Availability Zones.
- **Task subnet validation fails:** confirm at least one resolved task subnet belongs to `vpc_id`. One or more task subnets are accepted for any `desired_count`; use multiple Availability Zones when workload resilience is required.
- **Invalid `for_each` or unknown-key planning error:** keep subnet values computed if needed, but construct fixed-length lists whose element count is known during planning.
- **Tasks cannot start or image pull fails:** verify caller-owned task-subnet route tables, NAT or proxy policy, DNS, HTTPS egress, Docker Hub reachability, and AWS Logs connectivity. The module does not validate route-table semantics.
- **Log initialization fails:** verify the symmetric KMS key ARN and that its policy grants `logs.<region>.amazonaws.com` `kms:Encrypt`, `kms:Decrypt`, `kms:ReEncrypt*`, `kms:GenerateDataKey*`, and `kms:Describe*`, constrained by `kms:ViaService`, source account, and the log-group ARN encryption context. Also verify network reachability and caller permissions.
- **ECS reports an execution-role authorization error:** grant the applying principal `iam:PassRole` only for the module-created task execution role, with `iam:PassedToService = ecs-tasks.amazonaws.com`; do not grant unrestricted `iam:PassRole`.
- **ALB access logs are absent:** verify the bucket is in the ALB Region, uses SSE-S3 rather than SSE-KMS, and has the correct prefix and regional Elastic Load Balancing log-delivery policy.
- **Targets stay unhealthy:** inspect ECS events and CloudWatch logs; confirm the image starts, the container listens on `container_port`, and task security-group ingress references the ALB security group.
- **Internal URL is unreachable:** confirm the ALB private addresses are reachable through implemented private F5 Distributed Cloud origin connectivity and bidirectional caller-owned routing. The module does not validate route tables; do not make the ALB public merely to bypass missing routing.
- **Internet-facing ALB is unreachable:** confirm each ALB subnet has a default route to an internet gateway and the client source is allowed by `allowed_ingress_cidrs`.
- **Apply stopped after creating resources:** preserve state and follow the partial-apply recovery procedure; do not repair state by manually deleting tracked resources.
