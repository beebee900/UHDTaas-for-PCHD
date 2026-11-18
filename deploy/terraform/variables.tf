variable "name" {
  description = "Name of the VM and its security group."
  type        = string
  default     = "atra-k8s"
}

variable "region" {
  description = "In-country region of the cloud provider (ATRA_RESIDENCY=NG)."
  type        = string
}

variable "image_name" {
  description = "Ubuntu 24.04 image of the provider."
  type        = string
}

variable "flavor_name" {
  description = "VM size with at least 16 GB RAM (design 02, 2.4, profile k8s)."
  type        = string
}

variable "network_name" {
  description = "Network the VM joins."
  type        = string
}

variable "ssh_public_key" {
  description = "OpenSSH public key of the operator."
  type        = string
}

variable "admin_cidrs" {
  description = "Networks allowed to reach SSH and the Kubernetes API."
  type        = list(string)
}

variable "device_cidrs" {
  description = "Networks of the devices and edge sites (MQTT over TLS, CoAP)."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "k3s_version" {
  description = "K3s release installed by cloud-init."
  type        = string
  default     = "v1.37.1+k3s1"
}
