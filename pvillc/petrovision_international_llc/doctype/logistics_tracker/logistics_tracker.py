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
		movement_type = self.movement_type or "Inward"
		rows = self.dn_details if movement_type == "Outward" else self.po_details
		if rows:
			total_percentage = sum(flt(row.allocation_percentage) for row in rows)
			if abs(total_percentage - 100.0) > 0.01:
				frappe.throw(_("The total allocation percentage must equal 100%. Currently it is {0}%.").format(total_percentage))


@frappe.whitelist()
def create_journal_entries(logistics_tracker_name, entry_type="all"):
	doc = frappe.get_doc("Logistics Tracker", logistics_tracker_name)
	movement_type = doc.movement_type or "Inward"
	is_outward = (movement_type == "Outward")
	rows = doc.dn_details if is_outward else doc.po_details

	if not rows:
		if is_outward:
			frappe.throw(_("Please add at least one Delivery Note in the Delivery Note Details table."))
		else:
			frappe.throw(_("Please add at least one Purchase Order in the PO Details table."))

	# Validate row fields and total allocation percentage
	total_percentage = sum(flt(row.allocation_percentage) for row in rows)
	if abs(total_percentage - 100.0) > 0.01:
		frappe.throw(_("The total allocation percentage must equal 100%. Currently it is {0}%.").format(total_percentage))

	for row in rows:
		if not row.cost_center:
			frappe.throw(_("Row {0}: Cost Center is required.").format(row.idx))

	# Build remark list of [Party, Document]
	doc_remarks_list = []
	for row in rows:
		if is_outward:
			doc_remarks_list.append(f"[{row.customer}, {row.delivery_note}]")
		else:
			doc_remarks_list.append(f"[{row.supplier}, {row.purchase_order}]")
	doc_remarks_str = ", ".join(doc_remarks_list)
	doc_type_label = "DNs" if is_outward else "POs"

	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company", limit=1)[0].name
	company_currency = frappe.get_cached_value("Company", company, "default_currency")

	# Account definitions
	freight_account = "Freight and Forwarding Charges - PVI"
	customs_duty_account = "Customs Duty Expense - PVI"
	import_vat_account = "Import VAT 5% - PVI"
	bayan_charges_account = "Bayan charges (customs) - PVI"
	admin_charges_account = "Customs clearing charges - PVI"
	admin_vat_account = "Input VAT 5% - PVI"
	
	default_payable_account = frappe.get_cached_value("Company", company, "default_payable_account")
	logistics_supplier_account = (
		frappe.db.get_value("Party Account", {"parent": doc.logistics_supplier, "company": company}, "account")
		or default_payable_account
	)
	customs_supplier_account = (
		frappe.db.get_value("Party Account", {"parent": doc.customs_supplier, "company": company}, "account")
		if doc.customs_supplier
		else None
	) or default_payable_account or logistics_supplier_account

	# Fetch default project control configs
	settings = frappe.get_doc("Project Control Settings")
	default_project = settings.company_overhead_project
	default_cc = settings.company_overhead_cost_center

	created_jes = []

	if entry_type == "freight" or (entry_type == "all" and not doc.separate_invoice_for_customs):
		if doc.freight_je_created:
			frappe.throw(_("Freight Journal Entry has already been created and submitted."))

		if flt(doc.actual_freight_charges) <= 0:
			if entry_type == "freight":
				frappe.throw(_("Actual Freight Charges must be greater than zero to create Freight Journal Entry."))
		else:
			je1_entries = []
			total_allocated_freight = 0.0

			for row in rows:
				ratio = flt(row.allocation_percentage) / 100.0
				allocated_freight = flt(doc.actual_freight_charges) * ratio
				total_allocated_freight += allocated_freight
				item_ref = f"(DN: {row.delivery_note})" if is_outward else f"(PO: {row.purchase_order})"

				if allocated_freight > 0:
					je1_entries.append({
						"account": freight_account,
						"debit_in_account_currency": allocated_freight,
						"project": row.project,
						"cost_center": row.cost_center,
						"user_remark": f"Allocated Freight Charge {item_ref}"
					})

			if total_allocated_freight > 0:
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
					f"Logistics Freight Invoice allocation - {doc.name}{invoice_tag} - {doc_type_label}: {doc_remarks_str}",
					bill_no=doc.freight_invoice_number,
					bill_date=doc.freight_invoice_date,
					logistics_tracker_name=doc.name
				)
				created_jes.append(je1.name)
				doc.db_set("freight_journal_entry", je1.name)

	if doc.is_customs_applicable and (entry_type == "customs" or (entry_type == "all" and not doc.separate_invoice_for_customs)):
		if doc.customs_je_created:
			frappe.throw(_("Customs & Admin Journal Entry has already been created and submitted."))

		total_customs_inputs = (
			flt(doc.customs_duty)
			+ flt(doc.import_vat)
			+ flt(doc.bayan_charges)
			+ flt(doc.admin_charges)
			+ flt(doc.admin_charge_input_vat)
		)

		if total_customs_inputs <= 0:
			if entry_type == "customs":
				frappe.throw(_("Customs / Admin charges must be greater than zero to create Customs Journal Entry."))
		else:
			je2_entries = []
			total_allocated_customs = 0.0

			for row in rows:
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

			if total_allocated_customs > 0:
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
					f"Logistics Customs / Admin Invoice allocation - {doc.name}{invoice_tag} - {doc_type_label}: {doc_remarks_str}",
					bill_no=doc.customs_duty_invoice_number,
					bill_date=doc.customs_duty_invoice_date,
					logistics_tracker_name=doc.name
				)
				created_jes.append(je2.name)
				doc.db_set("customs_journal_entry", je2.name)

	if not created_jes:
		frappe.throw(_("No Journal Entries were created. Please ensure charges (Actual Freight or Customs/Admin) are greater than zero."))

	return created_jes


def create_je_doc(company, company_currency, accounts, remark, bill_no=None, bill_date=None, logistics_tracker_name=None):
	je = frappe.new_doc("Journal Entry")
	je.company = company
	je.posting_date = today()
	je.custom_remark = 1
	je.remark = remark
	je.multi_currency = 0
	je.bill_no = bill_no
	je.bill_date = bill_date
	if hasattr(je, "custom_logistics_tracker") or logistics_tracker_name:
		je.set("custom_logistics_tracker", logistics_tracker_name)

	for entry in accounts:
		debit = flt(entry.get("debit_in_account_currency", 0.0))
		credit = flt(entry.get("credit_in_account_currency", 0.0))

		# Skip empty zero-value rows that violate ERPNext JE validation
		if debit <= 0 and credit <= 0:
			continue

		row = je.append("accounts", {
			"account": entry.get("account"),
			"project": entry.get("project"),
			"cost_center": entry.get("cost_center"),
			"debit_in_account_currency": debit,
			"credit_in_account_currency": credit,
			"party_type": entry.get("party_type"),
			"party": entry.get("party"),
			"user_remark": entry.get("user_remark", remark)
		})
		
		# Set exchange rate standard values
		row.exchange_rate = 1.0
		row.debit = debit
		row.credit = credit

	je.save()
	return je
