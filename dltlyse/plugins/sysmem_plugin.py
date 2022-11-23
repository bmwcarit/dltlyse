# Copyright (C) 2022. BMW Car IT GmbH. All rights reserved.
"""Parses DLT messages from the Monitor tool to gather system RAM usage"""
from csv import writer

from dltlyse.core.plugin_base import Plugin


class SysmemPlugin(Plugin):
    """Report system memory information"""

    message_filters = [("MON", "MEMS")]

    pathname = "sysmem_report.csv"
    lifecycle_csv_fields = ("lifecycle", "time", "mem_total", "mem_available", "buffers", "cached", "shared")

    field_mapping = {
        "MemTotal": "mem_total",
        "MemAvailable": "mem_available",
        "Buffers": "buffers",
        "Cached": "cached",
        "Shmem": "shared",
    }

    def __init__(self):
        self.csv_fileobj = None
        self.csv = None
        self.lifecycle = None
        self.min_mem_available = None
        super(SysmemPlugin, self).__init__()

    def new_lifecycle(self, ecu_id, lifecycle_id):
        """New device start"""
        if not self.csv:  # Only create the report file if this plugin is actually run
            self.csv_fileobj = open(self.pathname, "w")
            self.csv = writer(self.csv_fileobj)
            self.csv.writerow(self.lifecycle_csv_fields)
        self.lifecycle = lifecycle_id
        super(SysmemPlugin, self).new_lifecycle(ecu_id, lifecycle_id)

    def __call__(self, message):
        data = {"lifecycle": str(self.lifecycle), "time": message.tmsp}
        for combo_value in message.payload_decoded.split("MB"):
            if ":" not in combo_value:
                continue
            field, value = combo_value.split(":")
            field = field.strip()
            value = int(float(value) * 1024)
            if field == "MemAvailable":
                self.min_mem_available = min(value, self.min_mem_available) if self.min_mem_available else value
            if field in self.field_mapping:
                data[self.field_mapping[field]] = value
        self.csv.writerow([str(data.get(k, "")) for k in self.lifecycle_csv_fields])

    def end_lifecycle(self, ecu_id, lifecycle_id):
        """Device shut down"""
        self.csv_fileobj.flush()
        super(SysmemPlugin, self).end_lifecycle(ecu_id, lifecycle_id)

    def report(self):
        """Close report files and attach them to a test result"""
        self.csv.close()
        self.csv_fileobj.close()
        if self.min_mem_available < 1024 * 1024:
            self.add_result(message="Available memory dropped below 1Gb", state="failure")
        self.add_attachments(self.pathname)
