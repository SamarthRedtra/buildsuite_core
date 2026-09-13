# Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and contributors
# For license information, please see license.txt

"""Contract, material-planning, and manufacturing integration coverage."""

import frappe

from buildsuite_core.api import boq as boq_api
from buildsuite_core.tests.base import BuildSuiteTestCase


class TestContractManufacturing(BuildSuiteTestCase):
	def setUp(self):
		super().setUp()
		self.company = frappe.db.get_single_value("Global Defaults", "default_company") or self.company

	def _item(self, suffix, *, stock=True, manufactured=False):
		item_code = f"BS-TEST-{suffix}-{self._n}"
		item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		return frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": item_group,
				"stock_uom": "Nos",
				"is_stock_item": 1 if stock else 0,
				"is_purchase_item": 0 if manufactured or not stock else 1,
				"is_sales_item": 0 if stock else 1,
				"is_manufactured_item": 1 if manufactured else 0,
				"valuation_rate": 10 if stock else 0,
			}
		).insert(ignore_permissions=True)

	def _warehouse(self, label, project=None):
		abbr = frappe.db.get_value("Company", self.company, "abbr")
		return frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": f"BS Test {label} {self._n}",
				"company": self.company,
				"parent_warehouse": f"All Warehouses - {abbr}",
				"is_group": 0,
				"project": project,
			}
		).insert(ignore_permissions=True)

	def _bom(self, finished_item, component, component_qty=2):
		bom = frappe.get_doc(
			{
				"doctype": "BOM",
				"company": self.company,
				"item": finished_item.name,
				"quantity": 1,
				"is_active": 1,
				"is_default": 1,
				"items": [{"item_code": component.name, "qty": component_qty, "uom": "Nos"}],
			}
		).insert(ignore_permissions=True)
		bom.submit()
		return bom

	def _approved_boq(self, project, resources):
		boq = frappe.get_doc(
			{
				"doctype": "BOQ",
				"project": project.name,
				"title": f"Integration BOQ {self._n}",
			}
		).insert(ignore_permissions=True)
		group = frappe.get_doc(
			{
				"doctype": "BOQ Group",
				"boq": boq.name,
				"code": "A",
				"group_name": "Materials",
			}
		).insert(ignore_permissions=True)
		for index, (resource, qty) in enumerate(resources, start=1):
			item = frappe.get_doc(
				{
					"doctype": "BOQ Item",
					"boq": boq.name,
					"boq_group": group.name,
					"code": f"A.{index}",
					"description": resource.rate_name,
					"unit": "Nos",
					"planned_qty": qty,
					"rate": resource.current_rate,
				}
			).insert(ignore_permissions=True)
			frappe.get_doc(
				{
					"doctype": "BOQ Sub Item",
					"boq": boq.name,
					"boq_item": item.name,
					"rate_master": resource.name,
					"description": resource.rate_name,
					"qty_per_unit": 1,
					"qty": qty,
				}
			).insert(ignore_permissions=True)
		boq_api.submit_boq(boq.name)
		boq_api.approve_boq(boq.name)
		return frappe.get_doc("BOQ", boq.name)

	def _resource(self, item, supply_method, rate=10):
		return frappe.get_doc(
			{
				"doctype": "Construction Rate Master",
				"rate_code": f"BS-{supply_method[:3].upper()}-{frappe.generate_hash(length=5)}",
				"rate_name": f"{supply_method} resource",
				"category": "Material",
				"uom": "Nos",
				"current_rate": rate,
				"item_code": item.name,
				"supply_method": supply_method,
			}
		).insert(ignore_permissions=True)

	def test_boq_material_plan_explodes_bom_and_is_idempotent(self):
		from buildsuite_core.api.material_planning import (
			create_material_request,
			get_material_requirements,
		)

		project = self._make_project(company=self.company)
		direct = self._item("DIRECT")
		component = self._item("COMPONENT")
		finished = self._item("FINISHED", manufactured=True)
		self._bom(finished, component, component_qty=2)
		boq = self._approved_boq(
			project,
			[
				(self._resource(direct, "Purchase", 15), 3),
				(self._resource(finished, "Manufacture", 25), 4),
			],
		)

		plan = get_material_requirements(boq.name)
		by_item = {row["item_code"]: row for row in plan["requirements"]}
		self.assertEqual(by_item[direct.name]["qty"], 3)
		self.assertEqual(by_item[finished.name]["qty"], 4)
		self.assertEqual(by_item[component.name]["qty"], 8)

		warehouse = self._warehouse("Materials", project.name)
		purchase = create_material_request(boq.name, "Purchase", "2026-09-08", warehouse.name)
		manufacture = create_material_request(boq.name, "Manufacture", "2026-09-08", warehouse.name)
		self.assertEqual(
			{row.item_code for row in frappe.get_doc("Material Request", purchase["material_request"]).items},
			{direct.name, component.name},
		)
		self.assertEqual(
			frappe.get_doc("Material Request", manufacture["material_request"]).items[0].item_code,
			finished.name,
		)
		self.assertTrue(
			create_material_request(boq.name, "Purchase", "2026-09-08", warehouse.name)["already_created"]
		)

	def test_boq_contract_and_progress_invoice_keep_native_links(self):
		from buildsuite_core.api.contract import boq_to_sales_order, sales_order_to_progress_invoice

		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"BS Contract Customer {self._n}",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
			}
		).insert(ignore_permissions=True)
		project = self._make_project(company=self.company)
		project.customer = customer.name
		project.save(ignore_permissions=True)
		service = self._item("CONTRACT", stock=False)
		resource = self._resource(service, "Non-stock", 100)
		boq = self._approved_boq(project, [(resource, 10)])

		result = boq_to_sales_order(
			boq.name,
			frappe.as_json(
				{
					"items": [
						{
							"item_code": service.name,
							"description": "Progress work",
							"qty": 10,
							"rate": 100,
						}
					]
				}
			),
		)
		so = frappe.get_doc("Sales Order", result["sales_order"])
		self.assertEqual(so.custom_buildsuite_boq, boq.name)
		self.assertEqual(frappe.db.get_value("BOQ", boq.name, "sales_order"), so.name)
		so.submit()

		invoice_result = sales_order_to_progress_invoice(so.name, 50, "2026-09-08")
		invoice = frappe.get_doc("Sales Invoice", invoice_result["sales_invoice"])
		self.assertEqual(invoice.project, project.name)
		self.assertEqual(invoice.items[0].sales_order, so.name)
		self.assertEqual(invoice.items[0].so_detail, so.items[0].name)
		self.assertEqual(invoice.items[0].qty, 5)

	def test_manufacturing_wrappers_preserve_project(self):
		from buildsuite_core.api.manufacturing import (
			create_project_transfer,
			create_work_order,
			create_work_order_stock_entry,
		)

		project = self._make_project(company=self.company)
		component = self._item("WO-COMPONENT")
		finished = self._item("WO-FINISHED", manufactured=True)
		bom = self._bom(finished, component)
		source = self._warehouse("Raw")
		wip = self._warehouse("WIP")
		output = self._warehouse("Finished")
		project_warehouse = self._warehouse("Project", project.name)

		result = create_work_order(
			bom.name,
			5,
			project.name,
			self.company,
			source.name,
			wip.name,
			output.name,
			submit=1,
		)
		work_order = frappe.get_doc("Work Order", result["work_order"])
		self.assertEqual(work_order.project, project.name)
		stock_entry = create_work_order_stock_entry(work_order.name, "Material Transfer for Manufacture", 5)
		self.assertEqual(
			frappe.db.get_value("Stock Entry", stock_entry["stock_entry"], "project"), project.name
		)

		transfer = create_project_transfer(
			project.name,
			source.name,
			[{"item_code": component.name, "qty": 1}],
		)
		self.assertEqual(transfer["target_warehouse"], project_warehouse.name)

	def test_waterproofing_master_seed_is_idempotent(self):
		from buildsuite_core.api.waterproofing_seed import (
			COMPANY,
			CUSTOMER,
			RATES,
			setup_waterproofing_masters,
		)

		if not frappe.db.exists("Company", COMPANY) or not frappe.db.exists("Customer", CUSTOMER):
			self.skipTest("Waterproofing seed requires the configured company and customer")
		first = setup_waterproofing_masters()
		count_after_first = frappe.db.count("Construction Rate Master", {"name": ["in", list(RATES)]})
		second = setup_waterproofing_masters()
		self.assertEqual(first["assembly"], second["assembly"])
		self.assertEqual(first["bom"], second["bom"])
		self.assertEqual(first["workbook_sha256"], second["workbook_sha256"])
		self.assertEqual(
			first["workbook_sha256"], "86f9fa9d96be849e7e30301269ef5d13389c411d358d9f9a39fdf2852f1a66c6"
		)
		self.assertEqual(count_after_first, len(RATES))
		self.assertEqual(
			frappe.db.count("Construction Rate Master", {"name": ["in", list(RATES)]}),
			count_after_first,
		)

	def test_waterproofing_production_project_uses_valid_new_status(self):
		from buildsuite_core.api.waterproofing_seed import _project_status

		status = _project_status(uat=False)
		allowed = frappe.get_meta("Project").get_field("project_status").options.splitlines()
		self.assertEqual(status, "New")
		self.assertIn(status, allowed)
