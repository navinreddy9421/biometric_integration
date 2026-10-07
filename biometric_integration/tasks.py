import frappe


def sync_enabled_devices():
    """Sync enabled ZKTeco devices every 30 minutes when enabled in settings."""

    try:
        settings = frappe.get_single("Biometric Sync Settings")

        if not settings.enable_automatic_sync:
            return

        devices = frappe.get_all(
            "Biometric Device",
            filters={"enabled": 1},
            pluck="name",
        )

        sync_method = frappe.get_attr(
            "biometric_integration.api.zkteco.sync_device"
        )

        for device_name in devices:
            try:
                result = sync_method(device_name)
                frappe.logger("biometric_integration").info(
                    f"Scheduled sync for {device_name}: {result}"
                )
            except Exception:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"Biometric scheduled sync failed: {device_name}",
                )

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Biometric scheduled task failed",
        )
