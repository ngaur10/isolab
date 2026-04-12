# terraform/main.tf

# ── 1. VPC ──────────────────────────────────────
resource "aws_vpc" "lab_vpc" {
  cidr_block           = var.cidr_block
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags = {
    Name       = "lab-vpc-${var.user_id}-${var.lab_name}"
    user_id    = var.user_id
    lab        = var.lab_name
    managed-by = "lab-platform"
  }
}

resource "aws_subnet" "public_subnet" {
  vpc_id                  = aws_vpc.lab_vpc.id
  cidr_block              = cidrsubnet(var.cidr_block, 8, 0)
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = true
  tags = {
    Name    = "lab-public-subnet-${var.user_id}-${var.lab_name}"
    user_id = var.user_id
  }
}

resource "aws_subnet" "lab_subnet" {
  vpc_id            = aws_vpc.lab_vpc.id
  cidr_block        = cidrsubnet(var.cidr_block, 8, 1)
  availability_zone = "${var.aws_region}a"
  tags = {
    Name    = "lab-subnet-${var.user_id}-${var.lab_name}"
    user_id = var.user_id
  }
}

resource "aws_internet_gateway" "lab_igw" {
  vpc_id = aws_vpc.lab_vpc.id
  tags = { Name = "lab-igw-${var.user_id}-${var.lab_name}" }
}

resource "aws_eip" "nat_eip" {
  domain = "vpc"
  tags   = { Name = "lab-nat-eip-${var.user_id}-${var.lab_name}" }
}

resource "aws_nat_gateway" "lab_nat" {
  allocation_id = aws_eip.nat_eip.id
  subnet_id     = aws_subnet.public_subnet.id
  depends_on    = [aws_internet_gateway.lab_igw]
  tags          = { Name = "lab-nat-${var.user_id}-${var.lab_name}" }
}

resource "aws_route_table" "public_rt" {
  vpc_id = aws_vpc.lab_vpc.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.lab_igw.id
  }
  tags = { Name = "lab-public-rt-${var.user_id}-${var.lab_name}" }
}

resource "aws_route_table_association" "public_rt_assoc" {
  subnet_id      = aws_subnet.public_subnet.id
  route_table_id = aws_route_table.public_rt.id
}

resource "aws_route_table" "lab_rt" {
  vpc_id = aws_vpc.lab_vpc.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.lab_nat.id
  }
  route {
    cidr_block                = "10.0.0.0/16"
    vpc_peering_connection_id = aws_vpc_peering_connection.lab_to_vpn.id
  }
  route {
    cidr_block                = "10.8.0.0/16"
    vpc_peering_connection_id = aws_vpc_peering_connection.lab_to_vpn.id
  }
  tags = { Name = "lab-rt-${var.user_id}-${var.lab_name}" }
}

resource "aws_route_table_association" "lab_rt_assoc" {
  subnet_id      = aws_subnet.lab_subnet.id
  route_table_id = aws_route_table.lab_rt.id
}

resource "aws_security_group" "lab_sg" {
  name        = "lab-sg-${var.user_id}-${var.lab_name}"
  description = "Allow SSH from VPN server and VPN tunnel clients only"
  vpc_id      = aws_vpc.lab_vpc.id
  ingress {
    description = "SSH from VPN VPC"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }
  ingress {
    description = "SSH from VPN tunnel clients"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.8.0.0/16"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = {
    Name    = "lab-sg-${var.user_id}-${var.lab_name}"
    user_id = var.user_id
  }
}

resource "aws_iam_role" "lab_vm_role" {
  name = "lab-vm-role-${var.user_id}-${var.lab_name}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = { user_id = var.user_id, lab_name = var.lab_name }
}

resource "aws_iam_policy" "lab_vm_policy" {
  name = "lab-vm-policy-${var.user_id}-${var.lab_name}"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${var.lab_data_bucket}/${var.user_id}/*",
          "arn:aws:s3:::${var.lab_data_bucket}"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:PutLogEvents", "logs:CreateLogStream"]
        Resource = "arn:aws:logs:*:*:log-group:/labs/${var.user_id}/*"
      },
      { Effect = "Deny", Action = ["iam:*"],                  Resource = "*" },
      { Effect = "Deny", Action = ["ec2:TerminateInstances"],  Resource = "*" },
      { Effect = "Deny", Action = ["s3:DeleteBucket"],         Resource = "*" },
      { Effect = "Deny", Action = ["dynamodb:DeleteTable"],    Resource = "*" }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lab_vm_attach" {
  role       = aws_iam_role.lab_vm_role.name
  policy_arn = aws_iam_policy.lab_vm_policy.arn
}

resource "aws_iam_instance_profile" "lab_profile" {
  name = "lab-profile-${var.user_id}-${var.lab_name}"
  role = aws_iam_role.lab_vm_role.name
}

resource "aws_instance" "lab_vm" {
  ami                         = var.lab_ami_id
  instance_type               = "t3.small"
  subnet_id                   = aws_subnet.lab_subnet.id
  vpc_security_group_ids      = [aws_security_group.lab_sg.id]
  iam_instance_profile        = aws_iam_instance_profile.lab_profile.name
  key_name                    = var.admin_key_name
  associate_public_ip_address = false

  user_data = <<-EOF
    #!/bin/bash
    set -eux
    exec > /var/log/lab-setup.log 2>&1
    useradd -m -s /bin/bash labuser
    echo "labuser:${var.lab_password}" | chpasswd
    sed -i 's/^PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config
    sed -i 's/^#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
    grep -q "^PasswordAuthentication" /etc/ssh/sshd_config || echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config
    systemctl restart sshd
    echo "Lab VM ready for user: ${var.user_id}"
  EOF

  root_block_device {
    volume_size           = 20
    volume_type           = "gp3"
    delete_on_termination = true
  }

  tags = {
    Name       = "lab-vm-${var.user_id}-${var.lab_name}"
    user_id    = var.user_id
    lab        = var.lab_name
    managed-by = "lab-platform"
  }
}

resource "aws_vpc_peering_connection" "lab_to_vpn" {
  vpc_id      = aws_vpc.lab_vpc.id
  peer_vpc_id = var.vpn_vpc_id
  auto_accept = true
  tags = { Name = "peer-lab-${var.user_id}-${var.lab_name}-to-vpn" }
}

resource "aws_route" "vpn_to_lab" {
  route_table_id            = var.vpn_route_table_id
  destination_cidr_block    = var.cidr_block
  vpc_peering_connection_id = aws_vpc_peering_connection.lab_to_vpn.id
}
