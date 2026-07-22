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
		self.validate_percentages()

	def calculate_difference(self):
		expected = flt(self.expected_freight_charges)
		actual = flt(self.actual_freight_charges)
		self.difference = actual - expected

	def validate_percentages(self):
		if self.po_details:
			total_percentage = sum(flt(row.allocation_percentage) for row in self.po_details)
			if abs(total_percentage - 100.0) > 0.01:
				frappe.throw(_("The total allocation percentage must equal 100%. Currently it is {0}%.").format(total_percentage))


@frappe.whitelist()
def create_journal_entries(logistics_tracker_name, entry_type="all"):
	doc = frappe.get_doc("Logistics Tracker", logistics_tracker_name)
	
	if not doc.po_details:
		frappe.throw(_("Please add at least one Purchase Order in the PO Details table."))

	# Validate row fields and total allocation percentage
	total_percentage = sum(flt(row.allocation_percentage) for row in doc.po_details)
	if abs(total_percentage - 100.0) > 0.01:
		frappe.throw(_("The total allocation percentage must equal 100%. Currently it is {0}%.").format(total_percentage))

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
	
	logistics_supplier_account = frappe.db.get_value("Party Account", {"parent": doc.logistics_supplier, "company": company}, "account") or "Accounts Payable - PVI"
	customs_supplier_account = frappe.db.get_value("Party Account", {"parent": doc.customs_supplier, "company": company}, "account") or "Accounts Payable - PVI" if doc.customs_supplier else logistics_supplier_account

	# Fetch default project control configs
	settings = frappe.get_doc("Project Control Settings")
	default_project = settings.company_overhead_project
	default_cc = settings.company_overhead_cost_center

	created_jes = []

	if entry_type == "freight" or (entry_type == "all" and not doc.separate_invoice_for_customs):
		if doc.freight_je_created:
			frappe.throw(_("Freight Journal Entry has already been created."))

		je1_entries = []
		total_allocated_freight = 0.0

		for row in doc.po_details:
			ratio = flt(row.allocation_percentage) / 100.0
			allocated_freight = flt(doc.actual_freight_charges) * ratio
			total_allocated_freight += allocated_freight

			je1_entries.append({
				"account": freight_account,
				"debit_in_account_currency": allocated_freight,
				"project": row.project,
				"cost_center": row.cost_center,
				"user_remark": f"Allocated Freight Charge (PO: {row.purchase_order})"
			})

		je1_entries.append({
			"account": logistics_supplier_account,
			"party_type": "Supplier",
			"party": doc.logistics_supplier,
			"credit_in_account_currency": total_allocated_freight,
			"project": default_project,
			"cost_center": default_cc,
			"user_remark": f"Total Freight Charge Payable - Invoice: {doc.freight_invoice_number or ''}"
		})

		invoice_tag = f" - Invoice: {doc.freight_invoice_number}" if doc.freight_invoice_number else ""
		je1 = create_je_doc(
			company, 
			company_currency, 
			je1_entries, 
			f"Logistics Freight Invoice allocation - {doc.name}{invoice_tag} - POs: {po_remarks_str}",
			bill_no=doc.freight_invoice_number,
			bill_date=doc.freight_invoice_date
		)
		created_jes.append(je1.name)
		doc.db_set("freight_je_created", 1)

	if entry_type == "customs" or (entry_type == "all" and not doc.separate_invoice_for_customs):
		if doc.customs_je_created:
			frappe.throw(_("Customs & Admin Journal Entry has already been created."))

		je2_entries = []
		total_allocated_customs = 0.0

		for row in doc.po_details:
			ratio = flt(row.allocation_percentage) / 100.0
			
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
			"account": customs_supplier_account,
			"party_type": "Supplier",
			"party": doc.customs_supplier or doc.logistics_supplier,
			"credit_in_account_currency": total_allocated_customs,
			"project": default_project,
			"cost_center": default_cc,
			"user_remark": f"Total Customs/Admin Charges Payable - Invoice: {doc.customs_duty_invoice_number or ''}"
		})

		invoice_tag = f" - Invoice: {doc.customs_duty_invoice_number}" if doc.customs_duty_invoice_number else ""
		je2 = create_je_doc(
			company, 
			company_currency, 
			je2_entries, 
			f"Logistics Customs / Admin Invoice allocation - {doc.name}{invoice_tag} - POs: {po_remarks_str}",
			bill_no=doc.customs_duty_invoice_number,
			bill_date=doc.customs_duty_invoice_date
		)
		created_jes.append(je2.name)
		doc.db_set("customs_je_created", 1)

	return created_jes


def create_je_doc(company, company_currency, accounts, remark, bill_no=None, bill_date=None):
	je = frappe.new_doc("Journal Entry")
	je.company = company
	je.posting_date = today()
	je.custom_remark = 1
	je.remark = remark
	je.multi_currency = 0
	je.bill_no = bill_no
	je.bill_date = bill_date

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
	return je
