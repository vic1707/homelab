from ipaddress import ip_network


def networks_overlap(left: str, right: str) -> bool:
	return ip_network(left).overlaps(ip_network(right))


class FilterModule:
	def filters(self) -> dict[str, object]:
		return {"networks_overlap": networks_overlap}
