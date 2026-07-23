# -*- coding: utf-8 -*-
# Copyright (c) 2026, 4C Solutions and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order
from pvillc.petrovision_international_llc.doctype.proforma_invoice.proforma_invoice import make_payment_entry


class TestProformaInvoice(IntegrationTestCase):
	def setUp(self):
		# Create a test Sales Order
		self.so = make_sales_order()
		self.so.submit()

	def test_proforma_invoice_workflow(self):
		# Create Proforma Invoice for 30% of Sales Order value
		pi = frappe.new_doc("Proforma Invoice")
		pi.sales_order = self.so.name
		pi.posting_date = frappe.utils.today()
		pi.percentage = 30.0
		pi.save()

		# Verify amounts are calculated correctly on save/validate
		expected_advance = self.so.grand_total * 0.3
		self.assertEqual(pi.grand_total, self.so.grand_total)
		self.assertAlmostEqual(pi.advance_amount, expected_advance)
		self.assertEqual(pi.status, "Draft")

		# Submit Proforma Invoice
		pi.submit()
		self.assertEqual(pi.status, "Unpaid")

		# Create Payment Entry via whitelist API
		pe_doc = make_payment_entry(pi.name)
		
		# Set payment entry required fields
		pe_doc.reference_no = "REF-TEST-123"
		pe_doc.reference_date = frappe.utils.today()
		
		# Set bank account (we can fetch standard test bank account or set a default one)
		company = self.so.company
		bank_account = frappe.db.get_value("Account", {"account_type": "Bank", "company": company})
		if not bank_account:
			bank_account = frappe.db.get_value("Account", {"account_type": "Cash", "company": company})
		
		pe_doc.paid_to = bank_account
		pe_doc.paid_to_account_currency = frappe.get_cached_value("Account", bank_account, "account_currency")
		
		pe_doc.save()
		pe_doc.submit()

		# Check that Proforma Invoice status is updated to Paid
		pi.reload()
		self.assertEqual(pi.status, "Paid")

		# Cancel Payment Entry
		pe_doc.cancel()
		
		# Check that Proforma Invoice status is reverted to Unpaid
		pi.reload()
		self.assertEqual(pi.status, "Unpaid")
