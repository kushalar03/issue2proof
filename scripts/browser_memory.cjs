const { chromium } = require('/opt/codex/cua_node/lib/node_modules/playwright');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({headless: true, executablePath: '/usr/bin/chromium', args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const consoleErrors = [];
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  await page.goto('http://127.0.0.1:8040', {waitUntil: 'networkidle'});
  await page.locator('#access-token').fill('memory-ui-test-token-only');
  await page.locator('#sign-in').click();
  await page.waitForLoadState('networkidle');

  await page.getByText('Recorded live evidence').click();
  await page.getByRole('button', {name: 'Historical Werkzeug repair'}).click();
  await page.getByRole('button', {name: 'Create executable Memory Capsule'}).click();
  await page.getByText(/memory v\d+/).waitFor();

  await page.locator('#memory-query').fill('Windows device path safe join traversal');
  await page.locator('#search-memory').click();
  await page.getByText('Recalled behavior').waitFor();
  const searchText = await page.locator('#results').innerText();
  if (!searchText.includes('Werkzeug') && !searchText.toLowerCase().includes('safe_join')) {
    throw new Error('Lexical recall did not surface the Werkzeug behavior.');
  }

  const budget = await page.evaluate(async () => (await fetch('/api/budget')).json());
  if (budget.total_credit_usd !== 25 || budget.protected_reserve_usd !== 5) {
    throw new Error(`Unexpected budget policy: ${JSON.stringify(budget)}`);
  }
  await page.screenshot({path: 'submission/memory-application.png', fullPage: true});
  const validation = {
    validated_at: new Date().toISOString(),
    checks: {
      login: true,
      saved_evidence_to_memory: true,
      lexical_recall: true,
      budget_policy: true,
      browser_console_clean: consoleErrors.length === 0,
    },
    budget,
    console_errors: consoleErrors,
  };
  fs.writeFileSync('artifacts/memory-browser-validation.json', JSON.stringify(validation, null, 2) + '\n');
  await browser.close();
})().catch(error => { console.error(error); process.exitCode = 1; });
