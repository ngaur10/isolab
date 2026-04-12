**Isolab**

A cloud-based lab provisioning platform that dynamically creates fully isolated AWS environments per user on demand, similar to TryHackMe or AWS Training labs.

Each lab runs in its own VPC, is accessible only via VPN, and is automatically destroyed after a fixed duration to control cost.

**What It Does**

When a user requests a lab:

A dedicated VPC is created with a unique CIDR block
A lab EC2 instance is provisioned (no public IP)
VPN-only access is enforced via OpenVPN
SSH credentials are generated dynamically per session
VPC peering connects the lab to the VPN network
The entire environment is automatically destroyed after 60 minutes

Supports up to 254 concurrent isolated labs using CIDR pool management.

**Architecture Overview**
**Data Plane**

User → OpenVPN → VPN VPC (10.0.0.0/16)
                    │
               VPC Peering
                    │
        Lab VPC (10.x.0.0/16)
                    │
              EC2 Lab VM


Users connect via VPN and access lab VMs privately
Lab VMs have no public IPs
All access is restricted via security groups + VPN routing

**Control Plane**

FastAPI Orchestrator → Terraform CLI → AWS APIs
                                 │
                      S3 (state) + DynamoDB (locking)

The orchestrator handles API requests and lifecycle management
Terraform provisions and destroys AWS infrastructure
State is stored remotely using S3 with DynamoDB locking

The FastAPI orchestrator operates in the control plane and is not part of the user traffic path.


**Components**
1. FastAPI Orchestrator (orchestrator/)

Core backend service responsible for:

Handling API requests
Managing lab sessions
Allocating CIDR blocks
Generating SSH credentials
Triggering Terraform
Scheduling auto-destroy


| Method | Endpoint                 | Description          |
| ------ | ------------------------ | -------------------- |
| POST   | `/start-lab`             | Provision a new lab  |
| DELETE | `/stop-lab/{session_id}` | Destroy lab          |
| GET    | `/sessions`              | List active sessions |
| GET    | `/health`                | Health check         |



**2. Terraform (terraform/)**

Infrastructure-as-Code layer that provisions per-lab resources:

VPC (unique CIDR per user)
Public + private subnets
Internet Gateway + NAT Gateway
EC2 lab instance (t3.small)
Security Groups (VPN-only access)
IAM role (scoped permissions)
VPC Peering to VPN VPC

Each lab runs in a separate Terraform workspace.



**3. CIDR Pool (cidr_pool.py)**

Thread-safe allocator for unique network ranges:

Range: 10.1.0.0/16 → 10.254.0.0/16
Prevents overlapping VPC CIDRs
Supports up to 254 concurrent labs


**4. VPN Layer (OpenVPN)**
Deployed manually on EC2 (separate VPC: 10.0.0.0/16)
Users authenticate via certificates
Assigns client IPs in 10.8.0.0/16
Routes traffic to lab VPCs via peering


**Lab Lifecycle**
Start
User calls /start-lab
CIDR allocated
Terraform workspace created
AWS resources provisioned
SSH credentials generated
Lab details returned
Access
ssh labuser@<private-ip>

(Only works via VPN)

**Stop**
Manual: /stop-lab/{session_id}
Automatic: after 60 minutes

**Security Design**


No public IPs on lab VMs
VPN-only access enforced
SSH password generated per session (secrets.token_urlsafe)
IAM roles scoped per lab instance
Explicit deny policies for destructive actions
Input validation on all API parameters
Terraform state encrypted in S3


 **Tech Stack**

| Layer              | Technology                    |
| ------------------ | ----------------------------- |
| API                | Python, FastAPI, Uvicorn      |
| Infra Provisioning | Terraform (AWS Provider ~5.0) |
| Cloud              | AWS EC2, VPC, IAM             |
| Networking         | OpenVPN, VPC Peering          |
| State              | S3 + DynamoDB                 |
| Concurrency        | asyncio                       |
| Security           | IAM + VPN + SG rules          |



**Prerequisites**

Before running:

AWS
AWS account with permissions for:
EC2, VPC, IAM, S3, DynamoDB
S3 bucket for Terraform state
DynamoDB table for state locking
Local Machine
Python 3.10+
Terraform v1.5+
AWS CLI v2
VPN
OpenVPN server running on EC2
Public IP exported as:
export VPN_SERVER_IP=<your-ip>


**Setup**
git clone <repo>
cd lab-platform

python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

pip install -r requirements.txt

**Run API**
uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000



**Cost Considerations**

| Resource      | Cost                 |
| ------------- | -------------------- |
| EC2 t3.small  | ~$0.02/hr            |
| NAT Gateway   | ~$0.045/hr (per lab) |
| VPC / Peering | Free                 |


NAT Gateway is the largest cost driver.

**Limitations**

- Max 254 concurrent labs — CIDR pool is bounded by /16 blocks (10.1–10.254)
- Route table growth — VPC Peering adds one route per lab to the VPN VPC; 
  hits AWS limits at scale
- Per-lab NAT Gateway — cost scales linearly (~$0.045/hr each); 
  a shared egress model would be more efficient at scale
- Shared Terraform backend — all workspaces share one S3 bucket; 
  a misconfigured operation could affect multiple environments
- Manual VPN setup — OpenVPN server must be pre-deployed before the platform runs
