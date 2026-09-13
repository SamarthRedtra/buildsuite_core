from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from buildsuite_core.api.global_search import LIMIT, global_search


class TestGlobalSearch(UnitTestCase):
	def test_short_queries_do_not_hit_database(self):
		with patch("buildsuite_core.api.global_search.frappe.get_list") as get_list:
			self.assertEqual(global_search("x"), {"groups": []})
			get_list.assert_not_called()

	def test_groups_routes_and_limits(self):
		rows = [
			[
				frappe._dict(
					{
						"name": "BS-WP-001",
						"custom_project_id": "BS-WP-001",
						"project_name": "Sobha Lagoon",
						"customer": "Desert Leisure",
						"location": "Dubai",
					}
				)
			],
			[
				frappe._dict(
					{
						"name": "TASK-001",
						"subject": "Waterproofing",
						"project": "BS-WP-001",
						"status": "Open",
					}
				)
			],
			[
				frappe._dict(
					{
						"name": "WP-2026-001",
						"work_package_name": "Waterproofing Works",
						"code": "WP-WATERPROOFING",
						"project": "BS-WP-001",
						"status": "Planned",
					}
				)
			],
		]
		with patch("buildsuite_core.api.global_search.frappe.get_list", side_effect=rows) as get_list:
			result = global_search("water")

		self.assertEqual(
			[group["label"] for group in result["groups"]], ["Projects", "Tasks", "Work Packages"]
		)
		self.assertEqual(
			[group["results"][0]["route"] for group in result["groups"]],
			["/projects/BS-WP-001", "/tasks/TASK-001", "/work-packages/WP-2026-001"],
		)
		self.assertTrue(all(call.kwargs["limit_page_length"] == LIMIT for call in get_list.call_args_list))
		self.assertTrue(
			all(call.args[0] in {"Project", "Task", "Work Package"} for call in get_list.call_args_list)
		)
