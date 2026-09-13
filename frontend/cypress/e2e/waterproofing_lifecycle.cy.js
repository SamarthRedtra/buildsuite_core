const PROJECT = "BS-WP-UAT-001";

describe("Waterproofing UAT lifecycle", () => {
	beforeEach(() => cy.loginAs("admin"));

	it("reconciles PDC and manufacturing records and renders their workspaces", () => {
		cy.request({
			url: "/api/method/buildsuite_core.api.pdc.list_pdcs",
			qs: { project: PROJECT },
		}).then(({ body }) => {
			const statuses = Object.fromEntries(body.message.map((row) => [row.name, row.status]));
			expect(statuses).to.deep.include({
				"PDC-0001": "Cleared",
				"PDC-0002": "Bounced",
				"PDC-0003": "Cleared",
			});
		});

		cy.visitApp("/project-finance/pdc");
		cy.dt("page-title").should("contain", "Post-dated cheques");
		cy.contains("BS-WP-UAT-IN-01").should("be.visible");
		cy.contains("BS-WP-UAT-OUT-BOUNCE").should("be.visible");

		cy.request({
			url: "/api/method/buildsuite_core.api.manufacturing.get_manufacturing_workspace",
			qs: { project: PROJECT },
		}).then(({ body }) => {
			expect(body.message.work_orders.map((row) => row.name)).to.include("MFG-WO-2026-00055");
			expect(body.message.stock_entries.map((row) => row.name)).to.include("MAT-STE-2026-00119");
			expect(body.message.material_consumption.map((row) => row.name)).to.include(
				"MAT-STE-2026-00122"
			);
		});

		cy.visitApp("/stock");
		cy.dt("page-title").should("contain", "Materials & Manufacturing");
		cy.contains("MFG-WO-2026-00055").should("be.visible");
	});
});
