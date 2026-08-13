# Terraform — AWS Deployment

Deploys the Movie Search Platform to AWS on **ECS Fargate**.

> Orchestrator justification: ECS Fargate keeps operational overhead low (no
> control-plane/node management vs EKS) while comfortably running the handful of
> long-lived services in this platform. TODO: expand.

## Layout
- `modules/` — networking, compute (ECS), rds, ecr, alb, iam, monitoring, secrets
- `environments/` — `dev/` and `prod/` root configs (backend + tfvars)

## Usage (TODO)
```bash
cd terraform/environments/dev
terraform init
terraform plan
terraform apply
```

## Requirements checklist
- [ ] Secrets via AWS Secrets Manager (no hardcoded credentials)
- [ ] Tasks use IAM roles (no access keys)
- [ ] RDS in private subnets only
- [ ] ALB with HTTPS (ACM cert)
- [ ] Auto-scaling (CPU + memory)
- [ ] VPC Flow Logs enabled
- [ ] S3 backend + DynamoDB locking
- [ ] Tags: Environment, Project, ManagedBy
