import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";

const browser = await chromium.launch({ headless: true, channel: "chromium" });
const directory = process.env.SCREENSHOT_DIR || "/tmp/workoutbridge-browser";
await mkdir(directory, { recursive: true });
try {
  for (const width of [1440, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const state = {
      sources: [
        {
          id: "sample",
          name: "Training calendar",
          format: "finalsurge",
          timezone: "UTC",
        },
      ],
      connections: [
        { id: "sample", provider: "Garmin Connect", account: "123" },
      ],
      syncs: [
        {
          id: "sample",
          source: "sample",
          profile: "sample",
          last_preview: "2030-01-01T08:00:00Z",
          error: null,
        },
      ],
      history: [],
      plans: [
        {
          id: "sample",
          hash: "synthetic",
          account: "123",
          created: "2030-01-01T08:00:00Z",
          items: [
            {
              event: {
                title: "Run: 4 miles + 4 strides",
                date: "2030-01-02",
                description: "4 miles + 4 strides",
              },
              draft: {
                steps: [
                  { kind: "run", duration: 6437.376, unit: "meters" },
                  {
                    count: 4,
                    skip_last_recovery: false,
                    steps: [
                      {
                        kind: "run",
                        duration: null,
                        unit: "lap_button",
                        note: "stride",
                      },
                      { kind: "rest", duration: null, unit: "lap_button" },
                    ],
                  },
                ],
                unresolved: [],
              },
            },
            {
              event: {
                title:
                  "Warm up 10 min; 5 x 400 m in 1:45-1:50 with 2 min easy recovery; Cool down 8 min",
                date: "2030-01-04",
                description: "Synthetic long title",
              },
              draft: { steps: [], unresolved: [] },
            },
            {
              event: {
                title: "Long run with unspecified progression",
                date: "2030-01-06",
                description: "Review required",
              },
              draft: { steps: [], unresolved: ["Unspecified progression"] },
              error: "Review required",
            },
          ],
        },
      ],
    };
    await page.route("**/api/v1/state", (route) => route.fulfill({ json: state }));
    await page.route("**/api/v1/garmin/login", (route) =>
      route.fulfill({ json: { status: "idle" } }),
    );
    await page.goto(process.env.CHECK_URL || "http://localhost:8080");
    await page.getByText("Upcoming workouts").waitFor();
    assert.equal(
      await page
        .getByLabel("Select Long run with unspecified progression")
        .isDisabled(),
      true,
    );
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
      true,
      `Overflow at ${width}`,
    );
    await page.screenshot({
      path: `${directory}/workouts-${width}.png`,
      fullPage: true,
    });
    await page.getByLabel("Select Run: 4 miles + 4 strides").check();
    await page.getByRole("button", { name: "Review publication" }).click();
    await page.getByRole("dialog").waitFor();
    const bounds = await page.getByRole("dialog").boundingBox();
    assert(
      bounds && bounds.x >= 0 && bounds.x + bounds.width <= width,
      `Dialog overflow at ${width}`,
    );
    assert.equal(
      await page
        .getByRole("button", { name: "Close dialog" })
        .evaluate((el) => el === document.activeElement),
      true,
    );
    await page.screenshot({
      path: `${directory}/confirm-${width}.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "Close dialog" }).click();
    for (const name of ["Sources", "Connections", "Syncs", "History"]) {
      await page.getByRole("button", { name, exact: true }).click();
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
        true,
        `${name} overflow at ${width}`,
      );
    }
    await page
      .getByRole("button", { name: "Connections", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Connect Garmin", exact: true })
      .click();
    await page.getByLabel("Garmin email").waitFor();
    let modal = await page.getByRole("dialog").boundingBox();
    assert(modal && modal.x >= 0 && modal.x + modal.width <= width);
    await page.screenshot({
      path: `${directory}/garmin-${width}.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "Close dialog" }).click();
    await page.getByRole("button", { name: "Syncs", exact: true }).click();
    await page.getByLabel("Automatic publishing for sample").click();
    await page
      .getByRole("button", { name: "Enable and publish now" })
      .waitFor();
    modal = await page.getByRole("dialog").boundingBox();
    assert(modal && modal.x >= 0 && modal.x + modal.width <= width);
    await page.screenshot({
      path: `${directory}/automatic-${width}.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "Close dialog" }).click();
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log(
    "Desktop/mobile UI checks passed; synthetic screenshots:",
    directory,
  );
} finally {
  await browser.close();
}
