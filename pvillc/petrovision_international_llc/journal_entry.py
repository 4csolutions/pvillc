# -*- coding: utf-8 -*-
# Copyright (c) 2026, 4C Solutions and contributors
# For license information, please see license.txt

import frappe

def validate_journal_entry(doc, method=None):
	default_project = None
	for row in doc.accounts:
		if not row.project:
			if row.reference_type == "Asset" and row.reference_name:
				project = frappe.db.get_value("Asset", row.reference_name, "project")
				if project:
					row.project = project
					continue
			
			if doc.voucher_type == "Depreciation Entry":
				if not default_project:
					default_project = frappe.db.get_single_value("Project Control Settings", "company_overhead_project")
				if default_project:
					row.project = default_project


def on_submit_journal_entry(doc, method=None):
	update_logistics_tracker_status(doc, is_submitted=True)


def on_cancel_journal_entry(doc, method=None):
	update_logistics_tracker_status(doc, is_submitted=False)


def update_logistics_tracker_status(doc, is_submitted=True):
	tracker_name = getattr(doc, "custom_logistics_tracker", None)
	if not tracker_name:
		return

	if not frappe.db.exists("Logistics Tracker", tracker_name):
		return

	tracker = frappe.get_doc("Logistics Tracker", tracker_name)
	status_value = 1 if is_submitted else 0

	if tracker.freight_journal_entry == doc.name:
		tracker.db_set("freight_je_created", status_value)

	if tracker.customs_journal_entry == doc.name:
		tracker.db_set("customs_je_created", status_value)





