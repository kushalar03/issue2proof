const { chromium } = require('/opt/codex/cua_node/lib/node_modules/playwright');
const fs = require('fs');

(async () => {
  fs.rmSync('submission/memory-raw-video', {recursive: true, force: true});
  const browser = await chromium.launch({
    headless: true,
    executablePath: '/usr/bin/chromium',
    args: ['--no-sandbox'],
  });
  const context = await browser.newContext({
    bypassCSP: true,
    viewport: {width: 1600, height: 1000},
    recordVideo: {dir: 'submission/memory-raw-video', size: {width: 1600, height: 1000}},
  });
  const page = await context.newPage();
  const pause = ms => page.waitForTimeout(ms);
  const started = Date.now();

  async function installGuide() {
    await page.addStyleTag({content: `
      html { scroll-behavior: smooth !important; }
      body.demo-workspace { height: 100vh; overflow: hidden; }
      body.demo-workspace .hero { display: none; }
      body.demo-workspace main { height: calc(100vh - 76px); padding-top: 16px; padding-bottom: 16px; }
      body.demo-workspace .workspace { height: calc(100vh - 108px); min-height: 0; }
      body.demo-workspace .workspace > aside,
      body.demo-workspace #results { height: 100%; overflow-y: auto; overscroll-behavior: contain; }
      body.demo-workspace footer { display: none; }
      #demo-cursor {
        position: fixed; left: 90px; top: 90px; z-index: 2147483647;
        width: 30px; height: 30px; pointer-events: none;
        border: 3px solid #fff; border-radius: 50%;
        background: #d96d45; box-shadow: 0 0 0 6px rgba(217,109,69,.27), 0 4px 14px rgba(20,35,29,.3);
        transition: left .65s cubic-bezier(.2,.8,.3,1), top .65s cubic-bezier(.2,.8,.3,1), transform .18s;
      }
      #demo-cursor::after { content: ''; position: absolute; left: 21px; top: 21px; width: 12px; height: 3px; background: #fff; transform: rotate(45deg); border-radius: 2px; }
      #demo-cursor.clicking { transform: scale(.66); }
      #demo-chapter {
        position: fixed; z-index: 2147483646; right: 30px; top: 96px; width: 330px;
        padding: 17px 20px; border: 1px solid rgba(255,255,255,.18); border-radius: 16px;
        color: #fffdf8; background: rgba(29,48,40,.94); box-shadow: 0 16px 38px rgba(19,34,28,.22);
        font: 700 18px/1.25 Inter, system-ui, sans-serif; pointer-events: none;
      }
      #demo-chapter small { display: block; margin-bottom: 5px; color: #afd0b8; font-size: 10px; letter-spacing: .16em; text-transform: uppercase; }
      .demo-focus { outline: 4px solid rgba(217,109,69,.74) !important; outline-offset: 5px !important; transition: outline-color .3s; }
    `});
    await page.evaluate(() => {
      const cursor = document.createElement('div'); cursor.id = 'demo-cursor';
      const chapter = document.createElement('div'); chapter.id = 'demo-chapter';
      chapter.innerHTML = '<small>Working demonstration</small>Repository memory in action';
      document.body.append(cursor, chapter);
    });
  }

  async function chapter(step, title) {
    console.log(`${((Date.now() - started) / 1000).toFixed(2)}s | ${step} | ${title}`);
    await page.evaluate(({step, title}) => {
      document.querySelector('#demo-chapter').innerHTML = `<small>${step}</small>${title}`;
    }, {step, title});
  }

  async function frame(locator, block = 'center') {
    await locator.scrollIntoViewIfNeeded();
    await locator.evaluate((element, position) => element.scrollIntoView({behavior: 'smooth', block: position, inline: 'nearest'}), block);
    await pause(900);
  }

  async function point(locator, hold = 1100) {
    await frame(locator);
    const box = await locator.boundingBox();
    if (!box) throw new Error('Cannot point to hidden element');
    await page.evaluate(({x, y}) => {
      const cursor = document.querySelector('#demo-cursor');
      document.querySelectorAll('.demo-focus').forEach(node => node.classList.remove('demo-focus'));
      cursor.style.left = `${x - 15}px`; cursor.style.top = `${y - 15}px`;
    }, {x: box.x + Math.min(box.width * .55, box.width - 18), y: box.y + Math.min(box.height * .5, box.height - 12)});
    await locator.evaluate(element => element.classList.add('demo-focus'));
    await pause(hold);
  }

  async function guidedClick(locator) {
    await point(locator, 900);
    await page.evaluate(() => document.querySelector('#demo-cursor').classList.add('clicking'));
    await pause(180);
    await locator.click();
    await page.evaluate(() => document.querySelector('#demo-cursor').classList.remove('clicking'));
    await pause(700);
  }

  await page.goto('http://127.0.0.1:8043');
  await page.locator('#access-token').fill('light-demo-review-only');
  await Promise.all([
    page.waitForNavigation({waitUntil: 'networkidle'}),
    page.locator('#sign-in').click(),
  ]);
  await installGuide();

  await chapter('1 · The idea', 'Turn repository guidance into replayable evidence');
  await point(page.locator('.hero h1'), 2200);
  await point(page.locator('.memory-loop'), 2500);

  await page.evaluate(() => document.body.classList.add('demo-workspace'));
  await chapter('2 · Integrate anywhere', 'Web workspace, coding agents, hooks, and CI');
  const integration = page.getByText('Use from agents and CI', {exact: true});
  await guidedClick(integration);
  await point(page.locator('.integration-section code').nth(0), 2200);
  await point(page.locator('.integration-section code').nth(1), 1800);
  await point(page.locator('.integration-section .integration-link'), 1200);

  await chapter('3 · Start with verified evidence', 'A real Werkzeug repair that passed its checks');
  await guidedClick(page.getByText('Recorded live evidence', {exact: true}));
  const werkzeug = page.getByRole('button', {name: 'Historical Werkzeug repair'});
  await guidedClick(werkzeug);
  await page.locator('#results .verdict').first().waitFor();
  await point(page.locator('#results .verdict').first(), 1800);
  await point(page.getByRole('button', {name: 'Create executable Memory Capsule'}), 3000);

  await chapter('4 · Remember', 'Freeze the claim, scope, provenance, and regression');
  await guidedClick(page.getByRole('button', {name: 'Create executable Memory Capsule'}));
  await page.getByText(/Agent recall index/).waitFor();
  await point(page.locator('#results .verdict').first(), 1800);
  await point(page.getByText('Agent recall index', {exact: true}), 2500);
  await point(page.getByText('Executable evidence', {exact: true}), 2800);

  await chapter('5 · Recall before a change', 'Find behavior affected by a Windows path refactor');
  const query = page.locator('#memory-query');
  await point(query, 1400);
  await query.fill('A refactor changes Windows path joining and reserved device names');
  await guidedClick(page.locator('#search-memory'));
  await page.getByText('Recalled behavior', {exact: true}).waitFor();
  const match = page.locator('#results .memory-card').first();
  await point(match, 3200);
  await guidedClick(match);
  await point(page.getByText('Known boundaries', {exact: true}), 2700);

  await chapter('6 · Replay and adjudicate', 'Fresh sandbox evidence catches a memory conflict');
  await guidedClick(page.getByText('Background investigations', {exact: true}));
  const jobs = page.locator('#jobs button');
  await guidedClick(jobs.first());
  await page.getByText('Recalled behavioral memory', {exact: true}).waitFor();
  const conflict = page.locator('#results .memory-card').first();
  await point(conflict, 3300);
  await point(page.getByText('Risk-adaptive model analysis', {exact: true}), 2400);
  const analyses = page.locator('#results .memory-card');
  await point(analyses.nth(1), 3000);
  await point(analyses.nth(2), 3200);

  await chapter('Result', 'Independent evidence follows every agent and every change');
  await pause(4500);
  await page.screenshot({path: 'submission/memory-conflict.png'});
  const video = page.video();
  await context.close();
  fs.renameSync(await video.path(), 'submission/memory-demo-screen.webm');
  await browser.close();
})().catch(error => { console.error(error); process.exitCode = 1; });
