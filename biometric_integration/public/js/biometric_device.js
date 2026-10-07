frappe.ui.form.on("Biometric Device", {
    refresh(frm) {
        if (frm.is_new()) {
            return;
        }

        frm.add_custom_button("Test Connection", () => {
            frappe.call({
                method: "biometric_integration.api.zkteco.test_connection",
                args: {
                    device_name: frm.doc.name
                },
                freeze: true,
                freeze_message: __("Connecting to ZKTeco...")
            }).then(r => {
                if (r.message && r.message.success) {
                    frappe.show_alert({
                        message: r.message.message,
                        indicator: "green"
                    });

                    frm.reload_doc();
                } else {
                    frappe.msgprint({
                        title: __("Connection Failed"),
                        message: r.message
                            ? r.message.message
                            : __("Unable to connect to the device."),
                        indicator: "red"
                    });
                }
            });
        });

        frm.add_custom_button("Sync Now", () => {
            frappe.confirm(
                __("Read attendance logs from this ZKTeco device and create Employee Checkins?"),
                () => {
                    frappe.call({
                        method: "biometric_integration.api.zkteco.sync_device",
                        args: {
                            device_name: frm.doc.name
                        },
                        freeze: true,
                        freeze_message: __("Synchronizing attendance...")
                    }).then(r => {
                        if (!r.message) {
                            frappe.msgprint(__("No response received."));
                            return;
                        }

                        const result = r.message;

                        frappe.msgprint({
                            title: __("Biometric Sync Result"),
                            indicator: result.success ? "green" : "red",
                            message: `
                                <b>Device Logs:</b> ${result.device_logs || 0}<br>
                                <b>Created Checkins:</b> ${result.created_checkins || 0}<br>
                                <b>Skipped Duplicates:</b> ${result.skipped_duplicates || 0}<br>
                                <b>Unknown Users:</b> ${result.unknown_users || 0}<br>
                                <b>Failed Logs:</b> ${result.failed_logs || 0}
                            `
                        });

                        frm.reload_doc();
                    });
                }
            );
        });
    }
});
