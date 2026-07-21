# -*- coding: utf-8 -*-
# Copyright (c) 2026, 4C Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today


class LogisticsTracker(Document):
	def validate(self):
		self.calculate_difference()

	def calculate_difference(self):
		expected = flt(self.expected_freight_charges)
		actual = flt(self.actual_freight_charges)
		self.difference = actual - expected


@frappe.whitelist()
def create_journal_entries(logistics_tracker_name):
	doc = frappe.get_doc("Logistics Tracker", logistics_tracker_name)
	
	if doc.journal_entry_created:
		frappe.throw(_("Journal Entries have already been created for this Logistics Tracker."))

	if not doc.po_details:
		frappe.throw(_("Please add at least one Purchase Order in the PO Details table."))

	# Validate row fields and compute total base value
	total_base_value = sum(flt(row.po_value_in_base_currency) for row in doc.po_details)
	if total_base_value <= 0:
		frappe.throw(_("The total grand total in base currency of the selected POs must be greater than zero."))

	for row in doc.po_details:
		if not row.cost_center:
			frappe.throw(_("Row {0}: Cost Center is required.").format(row.idx))

	# Build remark list of [PO Supplier, PO]
	po_remarks_list = []
	for row in doc.po_details:
		po_remarks_list.append(f"[{row.supplier}, {row.purchase_order}]")
	po_remarks_str = ", ".join(po_remarks_list)

	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company", limit=1)[0].name
	company_currency = frappe.get_cached_value("Company", company, "default_currency")

	# Account definitions
	freight_account = "Freight and Forwarding Charges - PVI"
	customs_duty_account = "Customs Duty Expense - PVI"
	import_vat_account = "Import VAT 5% - PVI"
	bayan_charges_account = "Bayan charges (customs) - PVI"
	admin_charges_account = "Customs clearing charges - PVI"
	admin_vat_account = "Input VAT 5% - PVI"
	supplier_account = frappe.db.get_value("Party Account", {"parent": doc.logistics_supplier, "company": company}, "account") or "Accounts Payable - PVI"

	created_jes = []
	if doc.separate_invoices_for_customs:
		# JE 1: Freight Charges
		je1_entries = []
		total_allocated_freight = 0.0

		for row in doc.po_details:
			ratio = flt(row.po_value_in_base_currency) / total_base_value
			allocated_freight = flt(doc.actual_freight_charges) * ratio
			total_allocated_freight += allocated_freight

			je1_entries.append({
				"account": freight_account,
				"debit_in_account_currency": allocated_freight,
				"project": row.project,
				"cost_center": row.cost_center,
				"user_remark": f"Allocated Freight Charge (PO: {row.purchase_order})"
			})

		# Fetch default project control configs
		settings = frappe.get_doc("Project Control Settings")
		default_project = settings.company_overhead_project
		default_cc = settings.company_overhead_cost_center

		je1_entries.append({
			"account": supplier_account,
			"party_type": "Supplier",
			"party": doc.logistics_supplier,
			"credit_in_account_currency": total_allocated_freight,
			"project": default_project,
			"cost_center": default_cc,
			"user_remark": f"Total Freight Charge Payable (Logistics Tracker: {doc.name})"
		})

		je1 = create_je_doc(company, company_currency, je1_entries, f"Logistics Freight Invoice allocation - {doc.name} - POs: {po_remarks_str}")
		created_jes.append(je1.name)

		# JE 2: Customs and Admin Charges
		je2_entries = []
		total_allocated_customs = 0.0

		for row in doc.po_details:
			ratio = flt(row.po_value_in_base_currency) / total_base_value
			
			allocated_duty = flt(doc.customs_duty) * ratio
			allocated_vat = flt(doc.import_vat) * ratio
			allocated_bayan = flt(doc.bayan_charges) * ratio
			allocated_admin = flt(doc.admin_charges) * ratio
			allocated_admin_vat = flt(doc.admin_charge_input_vat) * ratio

			row_total = allocated_duty + allocated_vat + allocated_bayan + allocated_admin + allocated_admin_vat
			total_allocated_customs += row_total

			if allocated_duty > 0:
				je2_entries.append({"account": customs_duty_account, "debit_in_account_currency": allocated_duty, "project": row.project, "cost_center": row.cost_center})
			if allocated_vat > 0:
				je2_entries.append({"account": import_vat_account, "debit_in_account_currency": allocated_vat, "project": row.project, "cost_center": row.cost_center})
			if allocated_bayan > 0:
				je2_entries.append({"account": bayan_charges_account, "debit_in_account_currency": allocated_bayan, "project": row.project, "cost_center": row.cost_center})
			if allocated_admin > 0:
				je2_entries.append({"account": admin_charges_account, "debit_in_account_currency": allocated_admin, "project": row.project, "cost_center": row.cost_center})
			if allocated_admin_vat > 0:
				je2_entries.append({"account": admin_vat_account, "debit_in_account_currency": allocated_admin_vat, "project": row.project, "cost_center": row.cost_center})

		je2_entries.append({
			"account": supplier_account,
			"party_type": "Supplier",
			"party": doc.logistics_supplier,
			"credit_in_account_currency": total_allocated_customs,
			"project": default_project,
			"cost_center": default_cc,
			"user_remark": f"Total Customs/Admin Charges Payable (Logistics Tracker: {doc.name})"
		})

		je2 = create_je_doc(company, company_currency, je2_entries, f"Logistics Customs / Admin Invoice allocation - {doc.name} - POs: {po_remarks_str}")
		created_jes.append(je2.name)

	else:
		# Single JE Booking All Expenses
		je_entries = []
		total_allocated = 0.0

		for row in doc.po_details:
			ratio = flt(row.po_value_in_base_currency) / total_base_value
			
			allocated_freight = flt(doc.actual_freight_charges) * ratio
			allocated_duty = flt(doc.customs_duty) * ratio
			allocated_vat = flt(doc.import_vat) * ratio
			allocated_bayan = flt(doc.bayan_charges) * ratio
			allocated_admin = flt(doc.admin_charges) * ratio
			allocated_admin_vat = flt(doc.admin_charge_input_vat) * ratio

			row_total = allocated_freight + allocated_duty + allocated_vat + allocated_bayan + allocated_admin + allocated_admin_vat
			total_allocated += row_total

			if allocated_freight > 0:
				je_entries.append({"account": freight_account, "debit_in_account_currency": allocated_freight, "project": row.project, "cost_center": row.cost_center})
			if allocated_duty > 0:
				je_entries.append({"account": customs_duty_account, "debit_in_account_currency": allocated_duty, "project": row.project, "cost_center": row.cost_center})
			if allocated_vat > 0:
				je_entries.append({"account": import_vat_account, "debit_in_account_currency": allocated_vat, "project": row.project, "cost_center": row.cost_center})
			if allocated_bayan > 0:
				je_entries.append({"account": bayan_charges_account, "debit_in_account_currency": allocated_bayan, "project": row.project, "cost_center": row.cost_center})
			if allocated_admin > 0:
				je_entries.append({"account": admin_charges_account, "debit_in_account_currency": allocated_admin, "project": row.project, "cost_center": row.cost_center})
			if allocated_admin_vat > 0:
				je_entries.append({"account": admin_vat_account, "debit_in_account_currency": allocated_admin_vat, "project": row.project, "cost_center": row.cost_center})

		# Fetch default project control configs
		settings = frappe.get_doc("Project Control Settings")
		default_project = settings.company_overhead_project
		default_cc = settings.company_overhead_cost_center

		je_entries.append({
			"account": supplier_account,
			"party_type": "Supplier",
			"party": doc.logistics_supplier,
			"credit_in_account_currency": total_allocated,
			"project": default_project,
			"cost_center": default_cc,
			"user_remark": f"Total Charges Payable (Logistics Tracker: {doc.name})"
		})

		je_single = create_je_doc(company, company_currency, je_entries, f"Logistics Allocation - {doc.name} - POs: {po_remarks_str}")
		created_jes.append(je_single.name)

	doc.db_set("journal_entry_created", 1)
	return created_jes


def create_je_doc(company, company_currency, accounts, remark):
	je = frappe.new_doc("Journal Entry")
	je.company = company
	je.posting_date = today()
	je.user_remark = remark
	je.multi_currency = 0

	for entry in accounts:
		row = je.append("accounts", {
			"account": entry.get("account"),
			"project": entry.get("project"),
			"cost_center": entry.get("cost_center"),
			"debit_in_account_currency": entry.get("debit_in_account_currency", 0.0),
			"credit_in_account_currency": entry.get("credit_in_account_currency", 0.0),
			"party_type": entry.get("party_type"),
			"party": entry.get("party"),
			"user_remark": entry.get("user_remark", remark)
		})
		
		# Set exchange rate standard values
		row.exchange_rate = 1.0
		if row.debit_in_account_currency > 0:
			row.debit = row.debit_in_account_currency
		if row.credit_in_account_currency > 0:
			row.credit = row.credit_in_account_currency

	je.save()
	return je
