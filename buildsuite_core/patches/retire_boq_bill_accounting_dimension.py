# Copyright (c) 2026, BuildSuite Core contributors

"""Remove the accounting dimension left behind by the retired BOQ Bill DocType."""

from buildsuite_core.legacy_retirement import remove_legacy_accounting_dimensions


def execute():
	remove_legacy_accounting_dimensions()
