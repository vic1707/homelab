def mycelium_interfaces(names, overrides, defaults, mgmt_vlan, parking_vlan):
	interfaces = []
	for name in names:
		port = defaults | overrides.get(name, {})
		interface = {
			"name": name,
			"mode": "access",
			"access_vlan": mgmt_vlan if port["role"] == "mgmt" else parking_vlan,
			"admin_state": "up" if port["enabled"] else "down",
		}
		if description := port.get("description"):
			interface["description"] = description
		interfaces.append(interface)
	return interfaces


class FilterModule:
	def filters(self):
		return {"mycelium_interfaces": mycelium_interfaces}
