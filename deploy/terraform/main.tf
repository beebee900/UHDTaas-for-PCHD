# One VM with Docker and K3s for the k8s profile (design 04, 4.2.3). Applying it needs a
# cloud account (person action P9).

provider "openstack" {
  region = var.region
}

locals {
  # Public APIs through the K3s ingress controller, devices on MQTT/TLS and CoAP.
  public_ports = [
    { protocol = "tcp", port = 80, cidrs = ["0.0.0.0/0"] },
    { protocol = "tcp", port = 443, cidrs = ["0.0.0.0/0"] },
    { protocol = "tcp", port = 8883, cidrs = var.device_cidrs },
    { protocol = "udp", port = 5683, cidrs = var.device_cidrs },
    { protocol = "tcp", port = 22, cidrs = var.admin_cidrs },
    { protocol = "tcp", port = 6443, cidrs = var.admin_cidrs },
  ]
  rules = flatten([
    for p in local.public_ports : [
      for cidr in p.cidrs : { key = "${p.protocol}-${p.port}-${cidr}", protocol = p.protocol,
      port = p.port, cidr = cidr }
    ]
  ])
}

resource "openstack_compute_keypair_v2" "operator" {
  name       = "${var.name}-operator"
  public_key = var.ssh_public_key
}

resource "openstack_networking_secgroup_v2" "atra" {
  name        = var.name
  description = "ATRA k8s profile: public APIs, device ingress, operator access"
}

resource "openstack_networking_secgroup_rule_v2" "ingress" {
  for_each          = { for r in local.rules : r.key => r }
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = each.value.protocol
  port_range_min    = each.value.port
  port_range_max    = each.value.port
  remote_ip_prefix  = each.value.cidr
  security_group_id = openstack_networking_secgroup_v2.atra.id
}

resource "openstack_compute_instance_v2" "atra" {
  name            = var.name
  image_name      = var.image_name
  flavor_name     = var.flavor_name
  key_pair        = openstack_compute_keypair_v2.operator.name
  security_groups = [openstack_networking_secgroup_v2.atra.name]
  user_data       = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    k3s_version = var.k3s_version
  })
  metadata = {
    residency = "NG"
    profile   = "k8s"
  }

  network {
    name = var.network_name
  }
}
