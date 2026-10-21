const { chromium } = require('/opt/codex/cua_node/lib/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({headless: true, executablePath: '/usr/bin/chromium', args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  await page.goto('http://127.0.0.1:8042', {waitUntil: 'networkidle'});
  await page.getByRole('heading', {name: 'Welcome back'}).waitFor();
  if (await page.locator('#app-shell').isVisible()) throw new Error('Application content is visible before sign-in.');
  await page.screenshot({path: 'submission/sign-in.png', fullPage: true});
  await page.locator('#access-token').fill('light-ui-review-only');
  await Promise.all([
    page.waitForNavigation({waitUntil: 'networkidle'}),
    page.locator('#sign-in').click(),
  ]);
  await page.getByRole('heading', {name: 'Your agents move on. Your codebase remembers.'}).waitFor();
  const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  if (background !== 'rgb(246, 242, 233)') throw new Error(`Unexpected page background: ${background}`);
  const headerPosition = await page.evaluate(() => getComputedStyle(document.querySelector('.site-header')).position);
  if (headerPosition === 'sticky' || headerPosition === 'fixed') throw new Error('Header can overlap page content.');
  await page.screenshot({path: 'submission/light-ui-home.png', fullPage: true});

  await page.getByText('Recorded live evidence').click();
  await page.getByRole('button', {name: 'Historical Werkzeug repair'}).click();
  await page.getByRole('button', {name: 'Create executable Memory Capsule'}).click();
  await page.getByText(/memory v\d+/).waitFor();
  await page.locator('#memory-query').fill('Windows reserved device names and path joining');
  await page.locator('#search-memory').click();
  await page.getByText('Recalled behavior').waitFor();
  await page.screenshot({path: 'submission/light-ui-memory.png', fullPage: true});

  await page.setViewportSize({width: 390, height: 844});
  await page.reload({waitUntil: 'networkidle'});
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  if (overflow) throw new Error('Mobile layout has horizontal overflow.');
  await page.screenshot({path: 'submission/light-ui-mobile.png', fullPage: true});
  await browser.close();
})().catch(error => { console.error(error); process.exitCode = 1; });
