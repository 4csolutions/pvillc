// Copyright (c) 2026, 4C Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on('Proforma Invoice', {
	refresh: function(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.status === 'Unpaid') {
			frm.add_custom_button(__('Payment'), function() {
				frappe.model.with_doctype('Payment Entry', function() {
					frappe.call({
						method: 'pvillc.petrovision_international_llc.doctype.proforma_invoice.proforma_invoice.make_payment_entry',
						args: {
							source_name: frm.doc.name
						},
						callback: function(r) {
							if (r.message) {
								var doc = frappe.model.sync(r.message);
								frappe.set_route('Form', 'Payment Entry', doc[0].name);
							}
						}
					});
				});
			}, __('Create'));
		}
	},
	sales_order: function(frm) {
		if (frm.doc.sales_order) {
			frappe.db.get_value('Sales Order', frm.doc.sales_order, ['customer', 'customer_name', 'company', 'grand_total'], (r) => {
				if (r) {
					frm.set_value('customer', r.customer);
					frm.set_value('customer_name', r.customer_name);
					frm.set_value('company', r.company);
					frm.set_value('grand_total', r.grand_total);
					frm.trigger('calculate_advance');
				}
			});
		} else {
			frm.set_value('customer', '');
			frm.set_value('customer_name', '');
			frm.set_value('company', '');
			frm.set_value('grand_total', 0.0);
			frm.set_value('advance_amount', 0.0);
		}
	},
	percentage: function(frm) {
		frm.trigger('calculate_advance');
	},
	calculate_advance: function(frm) {
		let advance = flt(frm.doc.grand_total) * (flt(frm.doc.percentage) / 100.0);
		frm.set_value('advance_amount', advance);
	}
});
