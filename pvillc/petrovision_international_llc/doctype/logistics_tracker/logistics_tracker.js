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

	refresh: function(frm) {
		if (frm.doc.docstatus === 0 && !frm.doc.journal_entry_created && !frm.is_new()) {
			frm.add_custom_button(__('Create Journal Entry'), function() {
				// Verify all rows have a cost center
				let missing_cost_center = false;
				if (!frm.doc.po_details || frm.doc.po_details.length === 0) {
					frappe.msgprint(__('Please add at least one Purchase Order in PO Details table.'));
					return;
				}
				frm.doc.po_details.forEach(row => {
					if (!row.cost_center) {
						missing_cost_center = true;
					}
				});
				if (missing_cost_center) {
					frappe.msgprint(__('Please select a Cost Center for all rows in the PO Details table before creating a Journal Entry.'));
					return;
				}

				frappe.confirm(
					__('Are you sure you want to generate Journal Entries for this Logistics Tracker?'),
					function() {
						frappe.call({
							method: 'pvillc.petrovision_international_llc.doctype.logistics_tracker.logistics_tracker.create_journal_entries',
							args: {
								logistics_tracker_name: frm.doc.name
							},
							freeze: true,
							callback: function(r) {
								if (!r.exc && r.message && r.message.length > 0) {
									frappe.show_alert({
										message: __('Journal Entries generated successfully as draft.'),
										indicator: 'green'
									});
									// Redirect to the newly created Journal Entry
									frappe.set_route('Form', 'Journal Entry', r.message[0]);
								}
							}
						});
					}
				);
			});
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
	supplier: function(frm, cdt, cdn) {
		// Clear row fields when supplier changes
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

function calculate_difference(frm) {
	let expected = flt(frm.doc.expected_freight_charges);
	let actual = flt(frm.doc.actual_freight_charges);
	frm.set_value('difference', actual - expected);
}
