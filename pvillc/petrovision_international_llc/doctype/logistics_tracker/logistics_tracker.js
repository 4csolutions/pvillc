// Copyright (c) 2026, 4C Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on('Logistics Tracker', {
	setup: function(frm) {
		frm.set_query('purchase_order', 'po_details', function(doc, cdt, cdn) {
			let row = locals[cdt][cdn];
			return {
				filters: {
					'supplier': row.supplier || ''
				}
			};
		});

		frm.set_query('cost_center', 'po_details', function(doc, cdt, cdn) {
			let row = locals[cdt][cdn];
			return {
				query: "project_controls.project_controls.doctype.project_boq.project_boq.get_cc_children_query",
				filters: {
					"project": row.project || ''
				}
			};
		});
	},

	logistics_supplier: function(frm) {
		if (frm.doc.logistics_supplier && !frm.doc.customs_supplier) {
			frm.set_value('customs_supplier', frm.doc.logistics_supplier);
		}
	},

	refresh: function(frm) {
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			// Helper to verify cost center and allocation percentages
			let validate_rows = function() {
				if (!frm.doc.po_details || frm.doc.po_details.length === 0) {
					frappe.msgprint(__('Please add at least one Purchase Order in PO Details table.'));
					return false;
				}
				let missing_cost_center = false;
				let total_percentage = 0.0;
				frm.doc.po_details.forEach(row => {
					if (!row.cost_center) {
						missing_cost_center = true;
					}
					total_percentage += flt(row.allocation_percentage);
				});
				if (missing_cost_center) {
					frappe.msgprint(__('Please select a Cost Center for all rows in the PO Details table.'));
					return false;
				}
				if (Math.abs(total_percentage - 100.0) > 0.01) {
					frappe.msgprint(__('The total allocation percentage must equal 100%. Currently it is ' + total_percentage + '%.'));
					return false;
				}
				return true;
			};

			let call_je_generation = function(entry_type, label) {
				if (!validate_rows()) return;
				frappe.confirm(
					__('Are you sure you want to generate the {0} Journal Entry for this Logistics Tracker?', [label]),
					function() {
						frappe.call({
							method: 'pvillc.petrovision_international_llc.doctype.logistics_tracker.logistics_tracker.create_journal_entries',
							args: {
								logistics_tracker_name: frm.doc.name,
								entry_type: entry_type
							},
							freeze: true,
							callback: function(r) {
								if (!r.exc && r.message && r.message.length > 0) {
									frappe.show_alert({
										message: __('Journal Entries generated successfully as draft.'),
										indicator: 'green'
									});
									frappe.set_route('Form', 'Journal Entry', r.message[0]);
								}
							}
						});
					}
				);
			};

			if (frm.doc.separate_invoice_for_customs) {
				if (!frm.doc.freight_je_created) {
					frm.add_custom_button(__('Create Freight Journal Entry'), function() {
						call_je_generation('freight', 'Freight');
					});
				}
				if (!frm.doc.customs_je_created) {
					frm.add_custom_button(__('Create Customs & Admin Journal Entry'), function() {
						call_je_generation('customs', 'Customs & Admin');
					});
				}
			} else {
				if (!frm.doc.freight_je_created && !frm.doc.customs_je_created) {
					frm.add_custom_button(__('Create Journal Entry (All Expenses)'), function() {
						call_je_generation('all', 'Combined Expenses');
					});
				}
			}
		}
	},

	expected_freight_charges: function(frm) {
		calculate_difference(frm);
	},

	actual_freight_charges: function(frm) {
		calculate_difference(frm);
	}
});

frappe.ui.form.on('Logistics Tracker PO', {
	po_details_add: function(frm, cdt, cdn) {
		// Evenly distribute allocation percentage when a new row is added
		distribute_percentage(frm);
	},

	po_details_remove: function(frm, cdt, cdn) {
		// Re-distribute allocation percentage when a row is removed
		distribute_percentage(frm);
	},

	supplier: function(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, 'purchase_order', '');
		frappe.model.set_value(cdt, cdn, 'project', '');
		frappe.model.set_value(cdt, cdn, 'cost_center', '');
		frappe.model.set_value(cdt, cdn, 'po_value', 0);
		frappe.model.set_value(cdt, cdn, 'po_value_in_base_currency', 0);
	},

	purchase_order: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.purchase_order) {
			frappe.db.get_value('Purchase Order', row.purchase_order, ['project', 'cost_center', 'grand_total', 'base_grand_total'], (r) => {
				if (r) {
					frappe.model.set_value(cdt, cdn, 'project', r.project || '');
					frappe.model.set_value(cdt, cdn, 'cost_center', r.cost_center || '');
					frappe.model.set_value(cdt, cdn, 'po_value', r.grand_total || 0);
					frappe.model.set_value(cdt, cdn, 'po_value_in_base_currency', r.base_grand_total || 0);
				}
			});
		} else {
			frappe.model.set_value(cdt, cdn, 'project', '');
			frappe.model.set_value(cdt, cdn, 'cost_center', '');
			frappe.model.set_value(cdt, cdn, 'po_value', 0);
			frappe.model.set_value(cdt, cdn, 'po_value_in_base_currency', 0);
		}
	}
});

function distribute_percentage(frm) {
	let rows = frm.doc.po_details || [];
	if (rows.length === 0) return;
	let equal_percentage = flt(100.0 / rows.length, 2);
	let sum = 0.0;
	rows.forEach((row, i) => {
		if (i === rows.length - 1) {
			// Adjust rounding error on the last row
			frappe.model.set_value(row.doctype, row.name, 'allocation_percentage', flt(100.0 - sum, 2));
		} else {
			frappe.model.set_value(row.doctype, row.name, 'allocation_percentage', equal_percentage);
			sum += equal_percentage;
		}
	});
}

function calculate_difference(frm) {
	let expected = flt(frm.doc.expected_freight_charges);
	let actual = flt(frm.doc.actual_freight_charges);
	frm.set_value('difference', actual - expected);
}
