output "address" {
  description = "Address of the VM on its network."
  value       = openstack_compute_instance_v2.atra.access_ip_v4
}
