import json
from datetime import datetime

import frappe
from zk import ZK


DUPLICATE_SECONDS = 10


def _parse_datetime(value):
    """Convert a datetime or ISO string to a naive datetime."""
    if not value:
        return None

    if isinstance(value, str):
        value = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

    if value.tzinfo is not None:
        value = value.replace(tzinfo=None)

    return value


def _get_zk_connection(device):
    """Create a connection to a ZKTeco device."""
    return ZK(
        device.device_ip,
        port=int(device.port or 4370),
        timeout=10,
        password=int(device.get("device_password") or 0),
        force_udp=False,
        ommit_ping=False,
    )


def _create_sync_log(
    device_name,
    started,
    status,
    device_logs=0,
    created=0,
    skipped=0,
    unknown=0,
    failed=0,
    error_message="",
    details=None,
):
    """Create a Biometric Sync Log record."""
    log = frappe.get_doc({
        "doctype": "Biometric Sync Log",
        "biometric_device": device_name,
        "sync_started": started,
        "sync_completed": frappe.utils.now_datetime(),
        "status": status,
        "device_logs": device_logs,
        "created_checkins": created,
        "skipped_duplicates": skipped,
        "unknown_users": unknown,
        "failed_logs": failed,
        "error_message": error_message,
        "details": json.dumps(details or {}, default=str),
    })

    log.insert(ignore_permissions=True)


@frappe.whitelist()
def test_connection(device_name):
    """Test the device connection and save device information."""
    device = frappe.get_doc("Biometric Device", device_name)

    if not device.enabled:
        frappe.throw("This biometric device is disabled.")

    if not device.device_ip:
        frappe.throw("Device IP is required.")

    conn = None

    try:
        conn = _get_zk_connection(device).connect()

        serial = conn.get_serialnumber()
        firmware = conn.get_firmware_version()
        platform = conn.get_platform()
        device_name_from_device = conn.get_device_name()

        try:
            total_logs = len(conn.get_attendance())
        except Exception:
            total_logs = 0

        device.data_xvfx = serial or ""
        device.data_cdxb = firmware or ""
        device.data_zepy = platform or ""
        device.data_ytkd = (
            device_name_from_device or ""
        )
        device.select_lswz = "Connected"
        device.datetime_sctd = frappe.utils.now_datetime()
        device.int_fbga = total_logs
        device.last_error = ""

        device.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": True,
            "message": "ZKTeco device connected successfully.",
            "device": {
                "serial_number": serial,
                "firmware_version": firmware,
                "platform": platform,
                "device_name": device_name_from_device,
                "total_logs": total_logs,
            },
        }

    except Exception as exc:
        device.select_lswz = "Error"
        device.datetime_sctd = frappe.utils.now_datetime()
        device.last_error = str(exc)
        device.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": False,
            "message": str(exc),
        }

    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass


@frappe.whitelist()
def sync_device(device_name, from_datetime=None, limit=None):
    """
    Synchronize ZKTeco attendance into ERPNext Employee Checkin.

    Mapping:
        ZKTeco user_id -> Employee.attendance_device_id

    If no sync cursor exists, establish a baseline at the latest
    device punch instead of importing the entire historical archive.

    Subsequent syncs process punches at or after the saved cursor.
    Existing check-ins are checked before insertion.
    """
    device = frappe.get_doc("Biometric Device", device_name)

    if not device.enabled:
        frappe.throw("This biometric device is disabled.")

    if not device.device_ip:
        frappe.throw("Device IP is required.")

    started = frappe.utils.now_datetime()
    conn = None

    created = 0
    skipped = 0
    unknown = 0
    failed = 0
    processed = 0
    details = {"unknown_user_ids": [], "errors": []}

    try:
        conn = _get_zk_connection(device).connect()

        all_logs = conn.get_attendance()
        total_device_logs = len(all_logs)

        device.select_lswz = "Connected"
        device.datetime_sctd = frappe.utils.now_datetime()
        device.int_fbga = total_device_logs
        device.last_error = ""

        # Explicit date overrides the saved cursor.
        cursor = _parse_datetime(
            from_datetime or device.datetime_qufu
        )

        # Safe first run: do not import the entire old archive.
        if cursor is None:
            if all_logs:
                latest_punch = max(
                    log.timestamp for log in all_logs
                )
                device.datetime_qufu = latest_punch
                device.last_successful_sync = frappe.utils.now_datetime()
                device.save(ignore_permissions=True)
                frappe.db.commit()

                _create_sync_log(
                    device_name=device.name,
                    started=started,
                    status="Success",
                    device_logs=0,
                    details={
                        "message": (
                            "Initial baseline established. "
                            "Historical punches were not imported."
                        ),
                        "baseline": latest_punch,
                        "device_total_logs": total_device_logs,
                    },
                )
                frappe.db.commit()

                return {
                    "success": True,
                    "message": (
                        "Initial baseline established. "
                        "No historical punches were imported. "
                        "Make a new punch and run Sync Now again."
                    ),
                    "device_logs": 0,
                    "created_checkins": 0,
                    "skipped_duplicates": 0,
                    "unknown_users": 0,
                    "failed_logs": 0,
                    "baseline": str(latest_punch),
                }

            device.last_successful_sync = frappe.utils.now_datetime()
            device.save(ignore_permissions=True)
            frappe.db.commit()

            _create_sync_log(
                device_name=device.name,
                started=started,
                status="Success",
                device_logs=0,
                details={"message": "Connected successfully; no device logs found."},
            )
            frappe.db.commit()

            return {
                "success": True,
                "message": "Connected successfully; no device logs found.",
                "device_logs": 0,
                "created_checkins": 0,
                "skipped_duplicates": 0,
                "unknown_users": 0,
                "failed_logs": 0,
            }

        # Inclusive cursor handles multiple punches sharing a timestamp.
        logs = sorted(
            [
                log for log in all_logs
                if log.timestamp >= cursor
            ],
            key=lambda log: log.timestamp,
        )

        if limit is not None:
            limit = int(limit)
            if limit < 1:
                frappe.throw("Limit must be a positive integer.")
            logs = logs[:limit]

        employees = frappe.get_all(
            "Employee",
            filters={
                "attendance_device_id": ["is", "set"]
            },
            fields=[
                "name",
                "attendance_device_id",
            ],
            limit_page_length=0,
        )

        employee_map = {
            str(employee.attendance_device_id): employee.name
            for employee in employees
        }

        last_user_punch = {}
        last_processed = cursor
        zkteco_device_id = f"ZKTeco-{device.device_ip}"

        for punch in logs:
            user_id = str(punch.user_id)
            punch_time = _parse_datetime(punch.timestamp)

            if punch_time is None:
                failed += 1
                details["errors"].append({
                    "user_id": user_id,
                    "error": "Invalid punch timestamp",
                })
                break

            previous = last_user_punch.get(user_id)
            if previous is not None:
                seconds = (punch_time - previous).total_seconds()
                if 0 <= seconds <= DUPLICATE_SECONDS:
                    skipped += 1
                    processed += 1
                    last_processed = max(last_processed, punch_time)
                    continue

            employee_name = employee_map.get(user_id)
            if not employee_name:
                unknown += 1
                if user_id not in details["unknown_user_ids"]:
                    details["unknown_user_ids"].append(user_id)
                last_user_punch[user_id] = punch_time
                processed += 1
                last_processed = max(last_processed, punch_time)
                continue

            existing = frappe.db.exists(
                "Employee Checkin",
                {"employee": employee_name, "time": punch_time},
            )
            if existing:
                skipped += 1
                last_user_punch[user_id] = punch_time
                processed += 1
                last_processed = max(last_processed, punch_time)
                continue

            day_start = punch_time.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day_end = punch_time.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )

            day_records = frappe.get_all(
                "Employee Checkin",
                filters={
                    "employee": employee_name,
                    "device_id": zkteco_device_id,
                    "time": ["between", [day_start, day_end]],
                },
                fields=["name", "time", "log_type"],
                order_by="time asc",
                limit_page_length=0,
            )

            in_records = [r for r in day_records if r.log_type == "IN"]
            out_records = [r for r in day_records if r.log_type == "OUT"]
            day_in = in_records[0] if in_records else None
            day_out = max(out_records, key=lambda r: r.time) if out_records else None

            try:
                if day_in is None:
                    clock = (punch_time.hour, punch_time.minute)
                    if not ((9, 30) <= clock <= (18, 30)):
                        skipped += 1
                    else:
                        doc = frappe.get_doc({
                            "doctype": "Employee Checkin",
                            "employee": employee_name,
                            "time": punch_time,
                            "log_type": "IN",
                            "device_id": zkteco_device_id,
                        })
                        doc.insert(ignore_permissions=True)
                        created += 1

                elif punch_time <= day_in.time:
                    skipped += 1

                elif day_out is None:
                    doc = frappe.get_doc({
                        "doctype": "Employee Checkin",
                        "employee": employee_name,
                        "time": punch_time,
                        "log_type": "OUT",
                        "device_id": zkteco_device_id,
                    })
                    doc.insert(ignore_permissions=True)
                    created += 1

                elif punch_time > day_out.time:
                    doc = frappe.get_doc("Employee Checkin", day_out.name)
                    doc.time = punch_time
                    doc.save(ignore_permissions=True)
                    details.setdefault("updated_checkouts", 0)
                    details["updated_checkouts"] += 1
                else:
                    skipped += 1

                last_user_punch[user_id] = punch_time
                processed += 1
                last_processed = max(last_processed, punch_time)

            except Exception as exc:
                failed += 1
                details["errors"].append({
                    "user_id": user_id,
                    "timestamp": str(punch_time),
                    "error": str(exc),
                })
                frappe.log_error(
                    frappe.get_traceback(),
                    "Biometric Checkin/Checkout Processing Failed",
                )
                break

        # Advance only through records handled in this run.
        if last_processed is not None:
            device.datetime_qufu = last_processed

        device.select_lswz = "Connected"
        device.datetime_sctd = frappe.utils.now_datetime()
        device.int_fbga = total_device_logs
        device.last_error = (
            details["errors"][0]["error"]
            if details["errors"]
            else ""
        )

        # Keep the successful-run timestamp separate from the punch cursor.
        if not failed:
            device.last_successful_sync = frappe.utils.now_datetime()

        device.save(ignore_permissions=True)

        if failed and created == 0 and skipped == 0:
            status = "Failed"
        elif failed or unknown:
            status = "Partial"
        else:
            status = "Success"

        _create_sync_log(
            device_name=device.name,
            started=started,
            status=status,
            device_logs=len(logs),
            created=created,
            skipped=skipped,
            unknown=unknown,
            failed=failed,
            error_message=device.last_error,
            details=details,
        )

        frappe.db.commit()

        return {
            "success": True,
            "message": "Biometric synchronization completed.",
            "device_logs": len(logs),
            "created_checkins": created,
            "skipped_duplicates": skipped,
            "unknown_users": unknown,
            "failed_logs": failed,
            "last_sync": str(device.datetime_qufu),
            "last_successful_sync": str(device.last_successful_sync or ""),
            "unknown_user_ids": details["unknown_user_ids"],
        }

    except Exception as exc:
        frappe.db.rollback()

        try:
            device = frappe.get_doc(
                "Biometric Device", device_name
            )
            device.select_lswz = "Error"
            device.datetime_sctd = frappe.utils.now_datetime()
            device.last_error = str(exc)
            device.save(ignore_permissions=True)

            _create_sync_log(
                device_name=device.name,
                started=started,
                status="Failed",
                created=created,
                skipped=skipped,
                unknown=unknown,
                failed=failed + 1,
                error_message=str(exc),
                details=details,
            )

            frappe.db.commit()
        except Exception:
            frappe.db.rollback()

        return {
            "success": False,
            "message": str(exc),
            "created_checkins": created,
            "skipped_duplicates": skipped,
            "unknown_users": unknown,
            "failed_logs": failed + 1,
        }

    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass