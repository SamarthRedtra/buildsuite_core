describe("Real company and global search", () => {
	const openSearch = () => {
		cy.get("body").trigger("keydown", {
			key: "k",
			code: "KeyK",
			ctrlKey: true,
			bubbles: true,
		});
	};

	beforeEach(() => {
		cy.login();
		cy.visitApp("/");
	});

	it("shows the active ERPNext company without ACME choices", () => {
		cy.get('[data-testid="active-company-badge"]')
			.should("contain", "Deltachem Middle East LLC")
			.and("not.contain", "ACME");
	});

	it("opens by keyboard and renders an empty state", () => {
		openSearch();
		cy.get('[data-testid="global-search"]').should("be.visible");
		cy.get('input[aria-label="Global search"]').type("zz-no-such-buildsuite-record");
		cy.contains("No matching projects, tasks, or work packages.").should("be.visible");
		cy.get('input[aria-label="Global search"]').trigger("keydown", {
			key: "Escape",
			code: "Escape",
			keyCode: 27,
		});
		cy.get('[data-testid="global-search"]').should("not.exist");
	});

	it("groups matching project results and navigates with Enter", () => {
		openSearch();
		cy.get('input[aria-label="Global search"]').type("Sobha Hartland");
		cy.contains("Projects").should("be.visible");
		cy.contains("Sobha Hartland II Mansion Lagoon").should("be.visible");
		cy.get('input[aria-label="Global search"]').trigger("keydown", {
			key: "Enter",
			code: "Enter",
			bubbles: true,
		});
		cy.location("pathname").should("match", /\/projects\/BS-WP-001$/);
	});

	it("shows an API failure without closing the palette", () => {
		cy.intercept("GET", "**/api/method/buildsuite_core.api.global_search.global_search*", {
			statusCode: 500,
			body: { _error_message: "Search unavailable" },
		});
		openSearch();
		cy.get('input[aria-label="Global search"]').type("waterproofing");
		cy.contains("Search unavailable").should("be.visible");
		cy.get('[data-testid="global-search"]').should("be.visible");
	});
});
