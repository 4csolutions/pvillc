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




