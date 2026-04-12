# terraform/output.tf

output "lab_vm_ip" {
  description = "Private IP of the lab VM (accessible via VPN)"
  value       = aws_instance.lab_vm.private_ip
}

output "vpc_id" {
  description = "VPC ID for this user session"
  value       = aws_vpc.lab_vpc.id
}

output "cidr_block" {
  description = "CIDR block assigned to this user"
  value       = var.cidr_block
}
