"""Strict parser for the supplied Waterproofing Consumption Sheet workbook."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

EXPECTED_SHA256 = "86f9fa9d96be849e7e30301269ef5d13389c411d358d9f9a39fdf2852f1a66c6"
COMPANY = "Deltachem Middle East LLC"
CUSTOMER_SOURCE = "Desert Group"
CUSTOMER = "Desert Leisure Swimming Pools LLC"
PROJECT_ID = "BS-WP-001"
PROJECT_NAME = "Sobha Hartland II Mansion Lagoon"
EXPECTED = {
	"area": Decimal("318"),
	"thickness": Decimal("3"),
	"man_days": Decimal("3.18"),
	"material": Decimal("46575.43636363637"),
	"labour": Decimal("3466.2"),
	"direct": Decimal("50041.63636363637"),
	"indirect": Decimal("9007.494545454545"),
	"consumables": Decimal("3002.498181818182"),
	"warranty": Decimal("4657.543636363637"),
	"cost": Decimal("66709.17272727273"),
	"selling": Decimal("86496"),
	"profit": Decimal("19786.82727272727"),
}


@dataclass(frozen=True)
class RateRow:
	code: str
	name: str
	category: str
	uom: str
	rate: Decimal
	coverage: Decimal
	source_row: int
	source_notes: str


@dataclass(frozen=True)
class WorkbookData:
	checksum: str
	project_name: str
	customer: str
	location: str
	start_date: date
	prepared_by: str
	revision: str
	values: dict
	rates: tuple[RateRow, ...]


def _decimal(value):
	return Decimal(str(value or 0))


def _assert_close(label, actual, expected, tolerance=Decimal("0.01")):
	if abs(actual - expected) > tolerance:
		raise ValueError(f"{label}: expected {expected}, got {actual}")


def _rate_rows(sheet):
	rows = []
	for row in range(7, 11):
		name = str(sheet.cell(row, 2).value).strip()
		rows.append(
			RateRow(
				f"WB-LAB-{name.upper().replace(' ', '-')}",
				name,
				"Labour",
				"Hour",
				_decimal(sheet.cell(row, 3).value),
				_decimal(sheet.cell(row, 4).value),
				row,
				str(sheet.cell(row, 6).value or ""),
			)
		)
	for prefix, category, row_numbers in (
		("PRI", "Material", range(15, 18)),
		("FIL", "Material", range(22, 24)),
		("POL", "Material", range(28, 32)),
	):
		for row in row_numbers:
			name = str(sheet.cell(row, 2).value).strip()
			uom = str(sheet.cell(row, 3).value).strip()
			coverage = _decimal(sheet.cell(row, 5).value)
			note = (
				"Coverage m²/unit"
				if prefix != "POL"
				else "Workbook kg per m² per 1mm; cached formula uses reciprocal"
			)
			rows.append(
				RateRow(
					f"WB-{prefix}-{name.upper().replace(' ', '-')}",
					name,
					category,
					uom,
					_decimal(sheet.cell(row, 4).value),
					coverage,
					row,
					note,
				)
			)
	if len(rows) != 13:
		raise ValueError(f"Expected 13 rate rows, found {len(rows)}")
	return tuple(rows)


def parse_workbook(path: str | Path, expected_checksum=EXPECTED_SHA256):
	path = Path(path).expanduser().resolve()
	checksum = hashlib.sha256(path.read_bytes()).hexdigest()
	if expected_checksum and checksum != expected_checksum:
		raise ValueError(f"Workbook checksum mismatch: expected {expected_checksum}, got {checksum}")
	workbook = load_workbook(path, read_only=True, data_only=True)
	try:
		if workbook.sheetnames != ["Project Costing", "Material & Rates", "Sheet1"]:
			raise ValueError(f"Unexpected workbook sheets: {workbook.sheetnames}")
		project = workbook["Project Costing"]
		rates = _rate_rows(workbook["Material & Rates"])
		values = {
			"area": _decimal(project["C16"].value),
			"thickness": _decimal(project["C17"].value),
			"man_days": _decimal(project["C18"].value),
			"material": _decimal(project["G25"].value),
			"labour": _decimal(project["G34"].value),
			"direct": _decimal(project["E39"].value),
			"indirect": _decimal(project["F39"].value),
			"consumables": _decimal(project["F40"].value),
			"warranty": _decimal(project["G48"].value),
			"cost": _decimal(project["G49"].value),
			"selling": _decimal(project["G52"].value),
			"profit": _decimal(project["G54"].value),
		}
		for key, expected in EXPECTED.items():
			_assert_close(key, values[key], expected)
		start = project["C10"].value
		if isinstance(start, datetime):
			start = start.date()
		data = WorkbookData(
			checksum=checksum,
			project_name=str(project["C7"].value or "").strip(),
			customer=str(project["C8"].value or "").strip(),
			location=str(project["C9"].value or "").strip(),
			start_date=start,
			prepared_by=str(project["C11"].value or "").strip(),
			revision=str(project["C12"].value or "").strip(),
			values=values,
			rates=rates,
		)
		if (
			data.project_name != PROJECT_NAME
			or data.customer != CUSTOMER_SOURCE
			or data.start_date != date(2026, 4, 6)
		):
			raise ValueError("Workbook project identity does not match the approved import")
		return data
	finally:
		workbook.close()


def serialise(data):
	result = asdict(data)
	result["start_date"] = data.start_date.isoformat()
	result["values"] = {key: str(value) for key, value in data.values.items()}
	result["rates"] = [
		{**asdict(row), "rate": str(row.rate), "coverage": str(row.coverage)} for row in data.rates
	]
	return result
