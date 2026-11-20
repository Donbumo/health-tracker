// Exercise the real Flask forms and browser with exclusively fictitious data.
const assert = require("node:assert/strict");
const { randomUUID } = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("playwright");

const base = "http://127.0.0.1:8067";
const fixturePath = path.join(__dirname, "../../examples/qa/nutrition-exchange/valid-explicit.json");
const evidence = process.env.QA_EXCHANGE_BROWSER_OUTPUT;
assert(evidence, "Provide an external output directory for fictitious QA screenshots.");

async function main() {
    await fs.mkdir(evidence, { recursive: true });
    const fixture = JSON.parse(await fs.readFile(fixturePath, "utf8"));
    const browser = await chromium.launch({ channel: "msedge", headless: true });
    const evidenceCases = [];
    try {
        for (const [surface, width] of [["desktop", 1366], ["mobile", 390]]) {
            const context = await browser.newContext({
                viewport: { width, height: 900 },
                permissions: ["clipboard-read", "clipboard-write"],
            });
            const page = await context.newPage();
            const errors = [];
            page.on("pageerror", error => errors.push(String(error)));
            page.on("response", response => { if (response.status() >= 500) errors.push(response.status()); });
            page.on("request", request => {
                if (request.method() === "POST") assert(!request.url().endsWith("/confirm"));
            });
            await page.goto(base + "/login");
            await page.locator("[name=username]").fill("htnx-fixture-" + surface);
            await page.locator("[name=password]").fill("only-fictional-exchange-password");
            await page.locator("input[type=submit],button[type=submit]").click();
            await page.goto(base + "/nutrition/import");
            assert(await page.getByRole("heading", { name: "Importar comidas con IA" }).isVisible());
            const copy = page.getByRole("button", { name: "Copiar prompt para IA" });
            await copy.focus();
            await page.keyboard.press("Enter");
            await page.getByText("Prompt copiado.", { exact: true }).waitFor();
            assert((await page.evaluate(() => navigator.clipboard.readText())).includes("health-tracker-nutrition"));
            const download = page.waitForEvent("download");
            await page.getByRole("link", { name: "Descargar ejemplo", exact: true }).click();
            assert.deepEqual(JSON.parse(await fs.readFile(await (await download).path(), "utf8")), fixture);
            await page.screenshot({ path: path.join(evidence, surface + "-entry.png") });

            await page.locator("#ni-exchange-json").fill(JSON.stringify(fixture));
            await page.getByRole("button", { name: "Revisar comidas pegadas" }).click();
            await page.getByText("4 listos · 0 pendientes · 0 inválidos", { exact: true }).waitFor();
            const state = await (await context.request.get(base + "/qa/state/" + page.url().split("/").pop())).json();
            assert.equal(state.groups, 4);
            assert.equal(state.nutrients, 30);
            assert.equal(Number(state.energy), 570.125);
            await page.locator("#record-1").getByText("Ver nutrientes y procedencia").click();
            assert(await page.locator("#record-1").getByText("Cromo ·", { exact: false }).isVisible());
            assert(!(await page.locator("[name=consent_consumed]").isChecked()));
            assert(await page.getByRole("button", { name: "Guardar todo" }).isEnabled());

            await page.goto(base + "/nutrition/import");
            await page.locator("#ni-exchange-json").fill(JSON.stringify({
                destino: "consumido", fecha: "2030-02-18",
                comidas: [{ tipo: "almuerzo", alimentos: [{
                    nombre: "Bocado ficticio QA", cantidad: { valor: "0.15", unidad: "kg" },
                    nutrición: { base: { cantidad: 100, unidad: "g" }, valores: { energía: { valor: 130, unidad: "kcal" } } },
                }] }],
            }));
            await page.getByRole("button", { name: "Revisar comidas pegadas" }).click();
            await page.getByText("1 listos · 0 pendientes · 0 inválidos", { exact: true }).waitFor();
            assert(await page.getByText("Aporte · 195 kcal", { exact: false }).first().isVisible());

            const file = structuredClone(fixture);
            file.note = "Lote ficticio del recorrido " + randomUUID();
            file.meals = [file.meals[0]];
            const source = file.meals[0].foods[0];
            file.meals[0].foods = Array.from({ length: 18 }, (_, i) => ({ ...structuredClone(source), name: "Alimento ficticio " + (i + 1) }));
            if (surface === "mobile") file.meals[0].foods[17].nutrition.basis.unit = "ml";
            for (const [i, food] of file.meals[0].foods.entries()) {
                if (surface === "desktop" || i < 17) delete food.nutrition.basis;
            }
            await page.goto(base + "/nutrition/import");
            await page.locator("#ni-exchange-file").setInputFiles({
                name: "lote-ficticio.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(file)),
            });
            await page.getByRole("button", { name: "Revisar archivo de comidas" }).click();
            const verify = page.getByRole("checkbox", { name: "Verifiqué estas bases en el registro de comidas." });
            await verify.check();
            await page.getByRole("button", { name: "Aplicar bases del grupo" }).click();
            const expected = surface === "desktop" ? [18, 0] : [17, 1];
            await page.getByText(expected[0] + " listos · " + expected[1] + " pendientes · 0 inválidos", { exact: true }).waitFor();
            if (surface === "mobile") {
                assert(await page.locator("#record-17").getByText("Declarado · 130 kcal", { exact: true }).isVisible());
                assert(await page.getByRole("button", { name: "Guardar todo" }).isDisabled());
                await page.locator("#record-17").evaluate(row => window.scrollTo(0, window.scrollY + row.getBoundingClientRect().top - 150));
                await page.screenshot({ path: path.join(evidence, "mobile-exception.png") });
                await page.evaluate(() => window.scrollTo(0, 0));
            }
            assert(!(await page.locator("[name=consent_consumed]").isChecked()));
            await page.screenshot({ path: path.join(evidence, surface + "-review.png") });
            for (const colorScheme of ["light", "dark"]) {
                await page.emulateMedia({ colorScheme });
                for (const point of [360, 390, 430, 768, 1024, 1366]) {
                    await page.setViewportSize({ width: point, height: 900 });
                    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
                }
            }
            assert.deepEqual(errors, []);
            evidenceCases.push({ surface, paste: 4, commonSpanish: 1, nutrients: 30, ready: expected[0], pending: expected[1], layouts: 12, errors: 0 });
            await context.close();
        }
    } finally {
        await browser.close();
    }
    await fs.writeFile(path.join(evidence, "results.json"), JSON.stringify(evidenceCases, null, 2));
    console.log(JSON.stringify(evidenceCases));
}

main().catch(error => { console.error(error); process.exitCode = 1; });
