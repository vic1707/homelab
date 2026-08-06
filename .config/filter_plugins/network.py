from ipaddress import ip_address, ip_network
from itertools import combinations

FIREWALL_FEATURE_SECTIONS = {
	"block_dot_doq": "block_{zone}_dot",
	"dhcp": "allow_{zone}_dhcp",
	"dns": "allow_{zone}_dns",
	"force_dns": "redirect_{zone}_dns",
	"internet": "{zone}_wan",
	"ntp": "allow_{zone}_ntp",
	"nut": "allow_{zone}_nut",
	"ping": "allow_{zone}_ping",
	"rescue_access": "rescue_{zone}",
	"router_management": "allow_{zone}_router",
}
FIREWALL_FEATURES = set(FIREWALL_FEATURE_SECTIONS)


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


def _network_for_ip(address: str | None, networks: list[dict]) -> str:
	if not address:
		return ""
	return next(
		(
			network["name"]
			for network in networks
			if network.get("subnet") and ip_address(address) in ip_network(network["subnet"])
		),
		"",
	)


def _firewall_endpoint(
	name: str, hosts: dict[str, dict], zones: set[str], networks: list[dict]
) -> tuple[str, str | None]:
	if name in hosts:
		address = hosts[name].get("ip")
		return _network_for_ip(address, networks), address
	if name in zones | {"rescue", "wan"}:
		return name, None
	return "", None


def firewall_section_ids(zones: list[dict]) -> list[str]:
	return [
		*[zone["name"] for zone in zones],
		*(
			FIREWALL_FEATURE_SECTIONS[feature].format(zone=zone["name"])
			for zone in zones
			for feature in zone.get("features", [])
		),
		*(name for zone in zones for name in zone.get("exceptions", {})),
	]


def firewall_config_errors(
	zones: list[dict], hosts: list[dict], networks: list[dict], nut_clients: list[str]
) -> list[str]:
	errors: list[str] = []
	host_map = {host["name"]: host for host in hosts}
	network_map = {network["name"]: network for network in networks}
	zone_names = [zone["name"] for zone in zones]
	zone_set = set(zone_names)
	exception_names = [name for zone in zones for name in zone.get("exceptions", {})]

	if len(zone_names) != len(zone_set):
		errors.append("firewall zone names must be unique")
	if len(exception_names) != len(set(exception_names)):
		errors.append("firewall exception names must be unique")

	for host in hosts:
		if host.get("ip") and not _network_for_ip(host["ip"], networks):
			errors.append(f"static host {host['name']} IP is outside all known networks")

	for zone in zones:
		zone_name = zone["name"]
		if zone_name not in network_map:
			errors.append(f"firewall zone {zone_name} has no matching network")
		elif network_map[zone_name].get("state") != "active" or network_map[zone_name].get("gateway_owner") != "fedex":
			errors.append(f"firewall zone {zone_name} is not an active Fedex-routed network")

		features = zone.get("features", [])
		unknown_features = sorted(set(features) - FIREWALL_FEATURES)
		if unknown_features:
			errors.append(f"firewall zone {zone_name} has unknown features: {', '.join(unknown_features)}")
		if len(features) != len(set(features)):
			errors.append(f"firewall zone {zone_name} has duplicate features")
		if "nut" in features:
			for client in nut_clients:
				if client in host_map and _network_for_ip(host_map[client].get("ip"), networks) != zone_name:
					errors.append(f"NUT firewall client {client} is outside zone {zone_name}")

		for rule_name, rule in zone.get("exceptions", {}).items():
			origin_zone, origin_ip = _firewall_endpoint(rule.get("origin", ""), host_map, zone_set, networks)
			if not origin_zone:
				errors.append(f"firewall exception {rule_name} has unknown origin")
				continue
			if origin_zone != zone_name:
				errors.append(f"firewall exception {rule_name} does not originate in zone {zone_name}")
			if rule["origin"] in host_map and not origin_ip:
				errors.append(f"firewall exception {rule_name} origin has no reserved IP")

			destinations = rule.get("destinations", [])
			if not destinations:
				errors.append(f"firewall exception {rule_name} has no destinations")
				continue

			resolved = [_firewall_endpoint(destination, host_map, zone_set, networks) for destination in destinations]
			if any(not destination_zone for destination_zone, _ in resolved):
				errors.append(f"firewall exception {rule_name} has an unknown destination")
				continue
			if len({destination_zone for destination_zone, _ in resolved}) != 1:
				errors.append(f"firewall exception {rule_name} destinations span multiple zones")
			if any(
				destination in host_map and not destination_ip
				for destination, (_, destination_ip) in zip(destinations, resolved)
			):
				errors.append(f"firewall exception {rule_name} destination has no reserved IP")
			if any(destination not in host_map for destination in destinations) and any(
				destination in host_map for destination in destinations
			):
				errors.append(f"firewall exception {rule_name} mixes host and zone destinations")

			ports = rule.get("ports", [])
			protocols = rule.get("protocols", [])
			if "ports" in rule and not ports:
				errors.append(f"firewall exception {rule_name} has an empty ports list")
			if "protocols" in rule and not protocols:
				errors.append(f"firewall exception {rule_name} has an empty protocols list")
			if ports and not protocols:
				errors.append(f"firewall exception {rule_name} specifies ports without protocols")
			if ports and set(protocols) - {"tcp", "udp"}:
				errors.append(f"firewall exception {rule_name} uses ports with a non-TCP/UDP protocol")

	for client in nut_clients:
		if client not in host_map or not host_map[client].get("ip"):
			errors.append(f"NUT firewall client {client} is unknown or has no reserved IP")

	return errors


def firewall_exception_options(
	rule: dict, hosts: list[dict], zone_names: list[str], networks: list[dict]
) -> dict:
	host_map = {host["name"]: host for host in hosts}
	zones = set(zone_names)
	src_zone, src_ip = _firewall_endpoint(rule["origin"], host_map, zones, networks)
	resolved_destinations = [
		_firewall_endpoint(destination, host_map, zones, networks) for destination in rule["destinations"]
	]
	dest_zone = resolved_destinations[0][0]
	dest_ips = [address for _, address in resolved_destinations if address]

	options = {
		"src": src_zone,
		"dest": dest_zone,
		"proto": rule.get("protocols") or ["all"],
		"target": "ACCEPT",
	}
	if src_ip:
		options["src_ip"] = src_ip
	if dest_ips:
		options["dest_ip"] = dest_ips
	if rule.get("ports"):
		options["dest_port"] = rule["ports"]
	return options


class FilterModule:
	def filters(self) -> dict[str, object]:
		return {
			"firewall_config_errors": firewall_config_errors,
			"firewall_exception_options": firewall_exception_options,
			"firewall_section_ids": firewall_section_ids,
			"icx_vlans": icx_vlans,
			"overlapping_networks": overlapping_networks,
			"subnet_netmask": subnet_netmask,
		}
