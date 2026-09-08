# -*- coding: utf-8 -*-
# Copyright (c) 2026, 4C Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class ProformaInvoice(Document):
	def validate(self):
		self.validate_sales_order()
		self.calculate_amounts()
		self.set_status()

	def validate_sales_order(self):
		if not self.sales_order:
			return

		so_doc = frappe.get_doc("Sales Order", self.sales_order)
		if so_doc.docstatus != 1:
			frappe.throw(_("Sales Order {0} must be in Submitted state.").format(self.sales_order))

		# Auto-fetch metadata if not fetched already
		self.customer = so_doc.customer
		self.customer_name = so_doc.customer_name
		self.company = so_doc.company
		self.grand_total = so_doc.grand_total

	def calculate_amounts(self):
		pct = flt(self.percentage)
		if pct <= 0 or pct > 100:
			frappe.throw(_("Percentage must be greater than 0 and less than or equal to 100."))

		self.advance_amount = flt(self.grand_total) * (pct / 100.0)

	def set_status(self):
		if self.docstatus == 0:
			self.status = "Draft"
		elif self.docstatus == 1:
			if self.status not in ["Paid", "Unpaid"]:
				self.status = "Unpaid"
		elif self.docstatus == 2:
			self.status = "Cancelled"

	def on_submit(self):
		self.db_set("status", "Unpaid")

	def on_cancel(self):
		self.db_set("status", "Cancelled")


@frappe.whitelist()
def make_payment_entry(source_name):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	doc = frappe.get_doc("Proforma Invoice", source_name)

	# generate payment entry
	pe = get_payment_entry("Sales Order", doc.sales_order, party_amount=doc.advance_amount)
	
	# Override fields
	pe.custom_proforma_invoice = doc.name
	pe.paid_amount = doc.advance_amount
	pe.received_amount = doc.advance_amount
	
	# Update references allocated_amount to match advance_amount
	for ref in pe.get("references"):
		if ref.reference_doctype == "Sales Order" and ref.reference_name == doc.sales_order:
			ref.allocated_amount = doc.advance_amount
			
	return pe


def update_proforma_invoice_status(doc, method):
	if getattr(doc, "custom_proforma_invoice", None):
		pi = frappe.get_doc("Proforma Invoice", doc.custom_proforma_invoice)
		if doc.docstatus == 1:
			pi.db_set("status", "Paid")
		elif doc.docstatus == 2:
			pi.db_set("status", "Unpaid")


def create_custom_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
	create_custom_fields({
		"Payment Entry": [
			{
				"fieldname": "custom_proforma_invoice",
				"label": "Proforma Invoice",
				"fieldtype": "Link",
				"options": "Proforma Invoice",
				"insert_after": "reference_date",
				"no_copy": 1
			}
		],
		"Journal Entry": [
			{
				"fieldname": "custom_logistics_tracker",
				"label": "Logistics Tracker",
				"fieldtype": "Link",
				"options": "Logistics Tracker",
				"insert_after": "bill_date",
				"no_copy": 1,
				"read_only": 1
			}
		]
	})
