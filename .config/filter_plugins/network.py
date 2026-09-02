from ipaddress import ip_address, ip_network
from itertools import combinations


def overlapping_networks(networks: list[str]) -> list[tuple[str, str]]:
	return [(left, right) for left, right in combinations(networks, 2) if ip_network(left).overlaps(ip_network(right))]


def subnet_netmask(subnet: str) -> str:
	return str(ip_network(subnet).netmask)


def vlan_ids(names: list[str], networks: list[dict]) -> list[int]:
	by_name = {network["name"]: network["vlan_id"] for network in networks}
	unknown = sorted(set(names) - by_name.keys())
	if unknown:
		raise ValueError(f"unknown network names: {', '.join(unknown)}")
	return [by_name[name] for name in names]


def dhcp_routes(destinations: list[str], gateway: str, networks: list[dict], zones: list[dict]) -> list[str]:
	zone_names = {zone["name"] for zone in zones}
	subnets = {
		network["name"]: network["subnet"]
		for network in networks
		if network["name"] in zone_names and network.get("subnet")
	}
	unknown = sorted(set(destinations) - subnets.keys())
	if unknown:
		raise ValueError(f"unknown DHCP route zones: {', '.join(unknown)}")
	return [f"{subnets[name]},{gateway}" for name in destinations]


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
	if name in zones | {"wan"}:
		return name, None
	return "", None


def firewall_section_ids(zones: list[dict], feature_sections: dict[str, str | list[str]]) -> list[str]:
	return [
		*[zone["name"] for zone in zones],
		*(
			pattern % zone["name"]
			for zone in zones
			for feature in zone.get("features", [])
			for pattern in (
				[feature_sections[feature]]
				if isinstance(feature_sections[feature], str)
				else feature_sections[feature]
			)
		),
		*(name for zone in zones for name in zone.get("exceptions", {})),
	]


def firewall_config_errors(
	zones: list[dict],
	hosts: list[dict],
	networks: list[dict],
	nut_clients: list[str],
	feature_sections: dict[str, str | list[str]],
) -> list[str]:
	errors: list[str] = []
	host_names = [host["name"] for host in hosts]
	host_ips = [host["ip"] for host in hosts if host.get("ip")]
	host_macs = [host["mac"].lower() for host in hosts if host.get("mac")]
	host_map = {host["name"]: host for host in hosts}
	network_map = {network["name"]: network for network in networks}
	zone_names = [zone["name"] for zone in zones]
	zone_set = set(zone_names)
	routed_networks = {network["name"] for network in networks if network.get("gateway")}
	exception_names = [name for zone in zones for name in zone.get("exceptions", {})]
	feature_names = set(feature_sections)

	if len(host_names) != len(set(host_names)):
		errors.append("static host names must be unique")
	if len(host_ips) != len(set(host_ips)):
		errors.append("static host IPs must be unique")
	if len(host_macs) != len(set(host_macs)):
		errors.append("static host MACs must be unique")
	endpoint_collisions = sorted(set(host_names) & (zone_set | {"wan"}))
	if endpoint_collisions:
		errors.append(f"static host names collide with firewall endpoints: {', '.join(endpoint_collisions)}")
	if len(zone_names) != len(zone_set):
		errors.append("firewall zone names must be unique")
	if len(exception_names) != len(set(exception_names)):
		errors.append("firewall exception names must be unique")
	for network in networks:
		try:
			dhcp_routes(
				network.get("dhcp", {}).get("routes", []), network.get("gateway", ""), networks, zones
			)
		except ValueError as error:
			errors.append(f"network {network['name']}: {error}")
	missing_zones = sorted(routed_networks - zone_set)
	if missing_zones:
		errors.append(f"routed networks have no firewall zone: {', '.join(missing_zones)}")

	for host in hosts:
		if host.get("ip") and not _network_for_ip(host["ip"], networks):
			errors.append(f"static host {host['name']} IP is outside all known networks")

	for zone in zones:
		zone_name = zone["name"]
		if zone_name not in network_map:
			errors.append(f"firewall zone {zone_name} has no matching network")
		elif network_map[zone_name].get("subnet") is None:
			errors.append(f"firewall zone {zone_name} has no routable network")

		features = zone.get("features", [])
		unknown_features = sorted(set(features) - feature_names)
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


def interface_list(ifaces: dict[str, dict]) -> list[dict]:
	return [{"name": name, **options} for name, options in ifaces.items()]


class FilterModule:
	def filters(self) -> dict[str, object]:
		return {
			"dhcp_routes": dhcp_routes,
			"firewall_config_errors": firewall_config_errors,
			"firewall_exception_options": firewall_exception_options,
			"firewall_section_ids": firewall_section_ids,
			"icx_vlans": icx_vlans,
			"interface_list": interface_list,
			"overlapping_networks": overlapping_networks,
			"subnet_netmask": subnet_netmask,
			"vlan_ids": vlan_ids,
		}
