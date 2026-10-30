const { chromium } = require('/opt/node-tools/node_modules/playwright');
const fs = require('fs');
const BASE = process.env.QA_DIR, URL = 'http://localhost:8765/opsys', MDP = 'mot-de-passe-direction-fictif';
const demain = new Date(Date.now() + 86400000), iso = demain.toISOString().slice(0, 19) + 'Z', J = iso.slice(0, 10);
const sortie = { console: [], alertes: [], etapes: [] };
(async () => {
  const nav = await chromium.launch({ args: ['--no-sandbox'] });
  for (const [largeur, nom] of [[1280, 'bureau'], [390, 'mobile']]) {
    const ctx = await nav.newContext({ viewport: { width: largeur, height: 900 } });
    const page = await ctx.newPage();
    page.on('console', m => sortie.console.push([nom, m.type(), m.text()]));
    page.on('pageerror', e => sortie.console.push([nom, 'pageerror', String(e)]));
    page.on('dialog', d => { sortie.alertes.push(d.message()); d.dismiss(); });
    await page.goto(`${URL}/connexion`);
    await page.fill('input[name=identifiant]', 'admin.fictif'); await page.fill('input[name=mot_de_passe]', MDP);
    await page.click('button[type=submit]'); await page.waitForLoadState();
    await page.goto(`${URL}/direction`);
    sortie.etapes.push([nom, 'dates vides', (await page.inputValue('input[name=connaissance]')) === '', (await page.inputValue('input[name=jour]')) === '']);
    await page.fill('input[name=connaissance]', iso); await page.fill('input[name=jour]', J);
    await page.click('form:not(.session) button[type=submit]'); await page.waitForLoadState();
    sortie.etapes.push([nom, 'tableau', page.url(), await page.locator('h2').allInnerTexts()]);
    await page.screenshot({ path: `${BASE}/direction-${nom}.png`, fullPage: true });
    sortie.etapes.push([nom, 'débordement horizontal', await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)]);
    await page.goto(`${URL}/direction/plans?connaissance=${encodeURIComponent(iso)}&jour=${J}`);
    sortie.etapes.push([nom, 'XSS rendu en texte', (await page.content()).includes('&lt;img src=x onerror'), await page.locator('img[src="x"]').count()]);
    await page.screenshot({ path: `${BASE}/plans-${nom}.png`, fullPage: true });
    fs.writeFileSync(`${BASE}/plans-${nom}.txt`, await page.locator('body').innerText());
    if (nom === 'bureau') {
      await page.fill('input[name=note]', 'client rappelé'); await Promise.all([page.waitForNavigation(), page.click('text=Noter le suivi')]);
      sortie.etapes.push([nom, 'après suivi', page.url(), (await page.locator('body').innerText()).match(/suivis_declares\s*\n?\s*\d+/)?.[0]]);
      await page.fill('form[action$="/plans/annuler"] input[name=motif]', 'abandon');
      await page.click('text=Annuler le plan');
      sortie.etapes.push([nom, 'annulation sans case cochée : reste sur la page', page.url().includes('/plans')]);
      await page.check('input[name=confirmer]');
      await Promise.all([page.waitForNavigation(), page.click('text=Annuler le plan')]);
      sortie.etapes.push([nom, 'après annulation', page.url(), (await page.locator('body').innerText()).includes('ANNULE'), await page.locator('form.commande').count()]);
    }
    for (const c of ['risques', 'sources', 'actions', 'revues', 'veille', 'scenarios']) {
      const r = await page.goto(`${URL}/direction/${c}` + (['risques', 'veille'].includes(c) ? `?connaissance=${encodeURIComponent(iso)}` : ''));
      sortie.etapes.push([nom, c, r.status()]);
    }
    await ctx.close();
  }
  await nav.close();
  console.log(JSON.stringify(sortie, null, 1));
})().catch(e => { console.log(JSON.stringify(sortie, null, 1)); console.error(String(e).slice(0,400)); process.exit(1); });
