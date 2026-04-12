# Lab Platform - Per-User Isolated Cloud Lab System

A cloud lab provisioning system that automatically creates fully isolated
AWS environments for each student on demand - similar to TryHackMe or
AWS Training, but built from scratch.

## What it does

When a student requests a lab, the system automatically:
- Creates a private AWS VPC just for them (isolated network)
- Launches an EC2 lab VM with SSH access via username + password
- Sets up VPC peering so the lab connects through OpenVPN server
- Auto-destroys everything after 60 minutes to control AWS costs
- Supports up to 254 concurrent labs via a managed CIDR pool

## Architecture

```
Student -> OpenVPN -> VPN VPC -> VPC Peering -> Lab VPC -> EC2 VM
                                      |
                              FastAPI Orchestrator
                                      |
                               Terraform (AWS)
```

| File | Role |
|---|---|
| orchestrator/main.py | FastAPI app - API routes, session management |
| orchestrator/cidr_pool.py | CIDR block manager (254 concurrent labs) |
| orchestrator/terraform.py | Runs Terraform commands from Python |
| terraform/main.tf | All AWS resources (VPC, EC2, IAM, peering) |
| terraform/variable.tf | All Terraform input variables |
| terraform/output.tf | Terraform outputs (lab VM IP) |
| terraform/backend.tf | Remote state - S3 + DynamoDB |
| vpn/setup.sh | OpenVPN server setup script |

## Security design

- No public IPs on lab VMs - only reachable through VPN
- Scoped IAM roles - S3 read + CloudWatch write only per lab
- Hard deny statements - labs cannot touch infrastructure
- Password-per-session - generated fresh, never reused
- Auto-destroy - labs cannot outlive their 60-minute window

## Tech stack

| Layer | Technology |
|---|---|
| API | Python 3.10+, FastAPI, Uvicorn |
| Infrastructure as Code | Terraform (AWS provider 5.0) |
| Cloud | AWS VPC, EC2, IAM, S3, DynamoDB |
| Networking | OpenVPN, VPC Peering, CIDR management |
| State storage | S3 + DynamoDB remote backend |

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | /start-lab | Provision a new isolated lab |
| DELETE | /stop-lab/{session_id} | Destroy a lab immediately |
| GET | /sessions | List all active sessions |
| GET | /health | Health check + active lab count |

## Setup

### Prerequisites
- Python 3.10+, Terraform v1.5+, AWS CLI v2
- AWS account with VPC, EC2, IAM, S3, DynamoDB permissions
- OpenVPN server on EC2 (see vpn/setup.sh)

### Install

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirement.txt
```

### Run

```powershell
$env:VPN_SERVER_IP = "your-vpn-server-ip"
uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000 --reload
```

API docs: http://localhost:8000/docs

## Cost estimate

| Resource | Cost |
|---|---|
| EC2 t3.small lab VM | ~$0.02/hr |
| VPC, subnets, peering | Free |
| Auto-destroy after 60 min | Max ~$0.02 per lab |
