from ipaddress import ip_network
from itertools import combinations


def overlapping_networks(networks: list[str]) -> list[tuple[str, str]]:
	return [(left, right) for left, right in combinations(networks, 2) if ip_network(left).overlaps(ip_network(right))]


def subnet_netmask(subnet: str) -> str:
	return str(ip_network(subnet).netmask)


def icx_vlans(networks: list[dict]) -> list[dict]:
	return [
		{"id": network["vlan_id"], "name": network["name"]}
		| (
			{
				"router_interface": network["vlan_id"],
				"ip_address": f"{network['addresses']['mycelium']}/{ip_network(network['subnet']).prefixlen}",
			}
			if network.get("addresses", {}).get("mycelium")
			else {}
		)
		for network in networks
	]


class FilterModule:
	def filters(self) -> dict[str, object]:
		return {
			"icx_vlans": icx_vlans,
			"overlapping_networks": overlapping_networks,
			"subnet_netmask": subnet_netmask,
		}
