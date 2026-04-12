# terraform/backend.tf

terraform {
  backend "s3" {
    bucket               = "platform-tf-states-namann"
    workspace_key_prefix = "workspaces"
    key                  = "terraform.tfstate"
    region               = "eu-north-1"
    dynamodb_table       = "tf-state-locks"
    encrypt              = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
