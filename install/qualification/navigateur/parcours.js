/* Parcours de la console dans un VRAI navigateur (Chromium piloté par playwright-core), sur l'instance fictive.
 *
 * Lancé par `lancer.py` (jamais à la main) : `node parcours.js CONFIG.json`. Écrit les constats dans cfg.resultats (JSON)
 * et des captures PNG horodatées dans cfg.captures. Chaque constat est { groupe, id, nom, ok, niveau, detail } :
 * niveau « bloquant » = un échec fait échouer le banc ; « info » = fait observé, consigné sans verdict (limites).
 * Aucun réseau hors de 127.0.0.1 : toute autre requête est refusée par le banc (route) et comptée.
 */
"use strict";
const fs = require("fs");
const path = require("path");

const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const pw = require(cfg.playwrightCore);
const MOTEUR = cfg.moteur || "chromium";
const chromium = pw[MOTEUR];
const CONTROLES = fs.readFileSync(path.join(__dirname, "controles_a11y.js"), "utf8");
const B = cfg.base; // ex. http://127.0.0.1:18700/opsys
const ORIGINE = new URL(B).origin;
const ids = JSON.parse(fs.readFileSync(path.join(cfg.dossier, "identifiants.json"), "utf8"));
const GROUPES = cfg.groupes && cfg.groupes.length ? new Set(cfg.groupes) : null;

const resultats = [];
let reseauExterne = [];
function constat(groupe, id, nom, ok, detail, niveau) {
  resultats.push({ groupe: groupe, id: id, nom: nom, ok: !!ok, niveau: niveau || "bloquant", detail: detail === undefined ? null : detail });
  const marque = ok ? "ok   " : (niveau === "info" ? "info " : "ECHEC");
  console.log("[" + marque + "] " + groupe + "/" + id + " " + nom + (ok ? "" : "  -> " + JSON.stringify(detail).slice(0, 300)));
}
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
let tailleCaptures = 0;
async function cap(page, nom) {
  const fichier = path.join(cfg.captures, cfg.horodatage + "-" + nom + ".png");
  await page.screenshot({ path: fichier, animations: "disabled", caret: "initial" });
  tailleCaptures += fs.statSync(fichier).size;
}
const SECRET_FICTIF = "fictif-" + require("crypto").randomBytes(18).toString("hex"); // valeur fictive, jamais écrite ailleurs

// -- contexte et espion réseau --------------------------------------------------------------------------------------
async function nouveauContexte(br, opts) {
  const ctx = await br.newContext(Object.assign({ viewport: { width: 1100, height: 640 }, locale: "fr-CA", serviceWorkers: "block" }, opts || {}));
  ctx.setDefaultTimeout(15000);
  const espion = { corps: [], urls: [], locations: [], consoles: [], violationsCsp: [], documents: [], dialogues: [], echecs: [] };
  await ctx.route("**/*", (route) => {
    const u = route.request().url();
    if (u.startsWith(ORIGINE) || (cfg.origines || []).some((o) => u.startsWith(o)) || u.startsWith("data:") || u.startsWith("about:")) return route.continue();
    reseauExterne.push(u);
    return route.abort();
  });
  ctx.on("page", (p) => brancher(p, espion));
  ctx.espion = espion;
  return ctx;
}
function brancher(p, espion) {
  p.on("response", async (r) => {
    espion.urls.push(r.url());
    const loc = r.headers()["location"];
    if (loc) espion.locations.push(loc);
    const ct = r.headers()["content-type"] || "";
    if (r.request().resourceType() === "document") {
      espion.documents.push({ url: r.url(), statut: r.status(), entetes: r.headers() });
    }
    if (/text|json|javascript|event-stream/.test(ct) && !/event-stream/.test(ct)) {
      try { espion.corps.push(await r.text()); } catch (e) { /* redirection ou corps indisponible */ }
    }
  });
  p.on("console", (m) => {
    const t = m.text();
    espion.consoles.push(m.type() + ": " + t);
    if (/Content Security Policy|violates the following/i.test(t)) espion.violationsCsp.push(t);
  });
  p.on("pageerror", (e) => espion.echecs.push("pageerror: " + String(e).slice(0, 200)));
  p.on("dialog", async (d) => { espion.dialogues.push(d.message()); await d.accept(); });
}
async function seConnecter(ctx, utilisateur, base) {
  const p = await ctx.newPage();
  await p.goto((base || B) + "/connexion");
  await p.fill("#identifiant", utilisateur);
  await p.fill("#mot_de_passe", ids[utilisateur]);
  await Promise.all([p.waitForURL(/\/departements$/), p.click("button[type=submit]")]);
  return p;
}
function lireEffets() {
  try { return fs.readFileSync(cfg.effets, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)); } catch (e) { return []; }
}

// -- groupes ---------------------------------------------------------------------------------------------------------
async function g_connexion(br) {
  const G = "connexion";
  const ctx = await nouveauContexte(br);
  const p = await ctx.newPage();
  const posts = [];
  p.on("request", (r) => { if (r.method() === "POST") posts.push(r.url()); });
  await p.goto(B + "/connexion");
  const r1 = await p.evaluate(() => ({
    h1: document.querySelector("h1").textContent, lang: document.documentElement.lang,
    labels: [...document.querySelectorAll("input")].map((i) => [i.id, (i.labels[0] || {}).textContent]),
    mdp: document.querySelector("#mot_de_passe").type, requis: [...document.querySelectorAll("input")].every((i) => i.required),
  }));
  constat(G, "page", "page de connexion : h1, lang=fr, deux champs étiquetés, mot de passe masqué",
    r1.h1 === "Connexion" && r1.lang === "fr" && r1.labels.length === 2 && r1.labels.every((l) => l[1]) && r1.mdp === "password" && r1.requis, r1);
  await cap(p, "01-connexion");

  await p.click("button[type=submit]");
  await dormir(300);
  const vide = await p.evaluate(() => ({ msg: document.querySelector("#identifiant").validationMessage, url: location.pathname }));
  constat(G, "soumission-vide", "formulaire vide : le navigateur bloque, aucun POST envoyé", posts.length === 0 && !!vide.msg && vide.url === "/opsys/connexion", { posts: posts.length, vide });

  await p.fill("#identifiant", "proprio-fictif");
  const faux = "mauvais-mot-de-passe-fictif-" + Date.now();
  await p.fill("#mot_de_passe", faux);
  const [rep] = await Promise.all([p.waitForResponse((r) => r.request().method() === "POST"), p.click("button[type=submit]")]);
  await p.waitForLoadState();
  const html = await p.content();
  const bandeau = await p.evaluate(() => { const m = document.querySelector(".message-erreur"); return m ? { texte: m.textContent, role: m.getAttribute("role") } : null; });
  const cookies = await ctx.cookies();
  constat(G, "echec-401", "mauvais mot de passe : 401 et message en français, aucun cookie de session",
    rep.status() === 401 && bandeau && bandeau.texte === "Identifiant ou mot de passe incorrect." && !cookies.some((c) => c.name === "opsys_session"), { statut: rep.status(), bandeau, cookies: cookies.map((c) => c.name) });
  constat(G, "echec-annonce", "le message d'échec est annoncé aux technologies d'assistance (role=alert)", bandeau && bandeau.role === "alert", bandeau);
  constat(G, "echec-secret-non-reaffiche", "le mot de passe saisi n'est jamais réaffiché ni renvoyé", !html.includes(faux) && (await p.inputValue("#mot_de_passe")) === "" && (await p.inputValue("#identifiant")) === "proprio-fictif", null);
  await cap(p, "02-connexion-echec");

  // Série d'échecs depuis le navigateur : constat honnête sur le verrouillage (il est externe : fail2ban, docs/ops/EXPLOITATION.md).
  const statuts = [];
  for (let i = 0; i < 12; i++) {
    await p.goto(B + "/connexion");
    await p.fill("#identifiant", "proprio-fictif");
    await p.fill("#mot_de_passe", "essai-force-brute-" + i);
    const [rr] = await Promise.all([p.waitForResponse((r) => r.request().method() === "POST"), p.click("button[type=submit]")]);
    statuts.push(rr.status());
  }
  constat(G, "serie-echecs", "12 échecs de suite : chaque essai reste refusé (401)", statuts.every((s) => s === 401), statuts);
  await p.goto(B + "/connexion");
  await p.fill("#identifiant", "proprio-fictif");
  await p.fill("#mot_de_passe", ids["proprio-fictif"]);
  const [ok] = await Promise.all([p.waitForResponse((r) => r.request().method() === "POST"), p.click("button[type=submit]")]);
  await p.waitForLoadState();
  constat(G, "pas-de-verrouillage-applicatif", "après 12 échecs, le bon mot de passe est ENCORE accepté : aucun verrouillage applicatif (la limitation relève de fail2ban en production, NON PROUVÉE ici)",
    ok.status() === 303 || p.url().endsWith("/departements"), { statut: ok.status(), url: p.url() }, "info");
  await p.waitForURL(/\/departements$/);
  const c = (await ctx.cookies()).find((x) => x.name === "opsys_session");
  const restant = c ? c.expires - Date.now() / 1000 : -1;
  constat(G, "cookie-drapeaux", "cookie de session : HttpOnly, Secure, SameSite=Strict, chemin /opsys, ~8 h",
    c && c.httpOnly && c.secure && c.sameSite === "Strict" && c.path === "/opsys" && restant > 28000 && restant <= 28800 + 5,
    c ? { httpOnly: c.httpOnly, secure: c.secure, sameSite: c.sameSite, path: c.path, restant_s: Math.round(restant) } : null);
  const visibleJs = await p.evaluate(() => document.cookie);
  constat(G, "cookie-invisible-js", "le cookie de session est invisible pour le JavaScript de la page (HttpOnly effectif)", !visibleJs.includes("opsys_session"), visibleJs);
  const entete = ((await ok.allHeaders())["set-cookie"] || "");
  constat(G, "set-cookie-brut", "l'en-tête Set-Cookie brut porte HttpOnly, Secure et SameSite=Strict", /httponly/i.test(entete) && /secure/i.test(entete) && /samesite=strict/i.test(entete), entete.replace(/opsys_session=[^;]+/, "opsys_session=***"));
  await p.goto(B + "/connexion");
  constat(G, "deja-connecte", "GET /connexion quand on est connecté : renvoie au tableau de bord", p.url().endsWith("/departements"), p.url());
  await ctx.close();
}

async function g_tableau(br) {
  const G = "tableau-de-bord";
  const ctx = await nouveauContexte(br);
  const p = await seConnecter(ctx, "proprio-fictif");
  const d = await p.evaluate(() => ({
    h1: document.querySelector("h1").textContent,
    nav: [...document.querySelectorAll("nav[aria-label=Sections] a")].map((a) => a.textContent),
    courant: (document.querySelector("nav a[aria-current=page]") || {}).textContent,
    cartes: document.querySelectorAll("article.carte").length,
    code: [...document.querySelectorAll(".carte-entete .code")].map((x) => x.textContent),
    pastille: ((document.querySelector(".pastille") || {}).textContent) || null,
    session: (document.querySelector(".session span") || {}).textContent,
  }));
  constat(G, "structure", "tableau de bord : h1, 17 onglets, onglet courant, une carte par département (10 réels + 1 fictif)",
    d.h1 === "Départements" && d.nav.length === 17 && d.courant === "Départements" && d.cartes === 11, d);
  constat(G, "pastille", "la pastille d'approbations annonce les 4 demandes en attente", d.pastille === "4", d.pastille);
  constat(G, "session-nommee", "la personne connectée est nommée", /proprio-fictif/.test(d.session || ""), d.session);
  await cap(p, "04-tableau-de-bord");
  await ctx.close();
}

async function g_approbations(br) {
  const G = "approbations";
  const ctx = await nouveauContexte(br);
  const p = await seConnecter(ctx, "proprio-fictif");
  await p.goto(B + "/approbations?statut=en_attente");
  const nb = await p.locator("article.carte").count();
  const carte = await p.evaluate(() => { const c = document.querySelector("article.carte"); return c ? c.textContent.replace(/\s+/g, " ").slice(0, 400) : null; });
  constat(G, "file", "la file « En attente » montre les 4 demandes N3 avec leurs arguments exacts", nb === 4 && /m9_qualif_publier_note/.test(carte) && /Note fictive/.test(carte), { nb, carte });
  await cap(p, "05-approbations-en-attente");
  const avant = lireEffets().length;
  const carteDe = (t) => p.locator("article.carte").filter({ hasText: t });
  const premiere = carteDe("Note fictive A du banc");
  // Confirmation du navigateur : l'effet n'arrive qu'après « OK ». On refuse d'abord (dialogue rejeté), puis on accepte.
  p.removeAllListeners("dialog");
  const messages = [];
  p.once("dialog", async (d) => { messages.push(d.message()); await d.dismiss(); });
  await premiere.getByRole("button", { name: "Approuver et exécuter" }).click();
  await dormir(500);
  constat(G, "confirmation-refusee", "la boîte de confirmation du navigateur, rejetée, n'exécute rien", lireEffets().length === avant && p.url().includes("/approbations"), { messages, effets: lireEffets().length });
  p.once("dialog", async (d) => { messages.push(d.message()); await d.accept(); });
  await Promise.all([p.waitForURL(/ok=executee/), premiere.getByRole("button", { name: "Approuver et exécuter" }).click()]);
  const bandeau = await p.evaluate(() => { const m = document.querySelector(".message"); return m ? { t: m.textContent, role: m.getAttribute("role") } : null; });
  const effets = lireEffets();
  constat(G, "approuver-effet", "approuver (après confirmation) exécute l'outil UNE fois : une ligne dans le fichier d'effets fictif",
    effets.length === avant + 1 && /Demande approuvée/.test(bandeau.t) && messages.length === 2, { effets: effets.length, bandeau, messages });
  await cap(p, "06-approbation-executee");
  await p.goto(B + "/approbations?statut=executee");
  constat(G, "historique-executee", "la demande apparaît dans « Exécutées » avec le statut Exécutée et le nom du signataire",
    (await p.locator("article.carte").count()) === 1 && /Exécutée/.test(await p.locator("article.carte").first().textContent()) && /proprio-fictif/.test(await p.locator("article.carte").first().textContent()), null);
  // refus
  await p.goto(B + "/approbations?statut=en_attente");
  await carteDe("Note fictive B du banc").getByRole("textbox").fill("Refus fictif du banc");
  await Promise.all([p.waitForURL(/ok=refusee/), carteDe("Note fictive B du banc").getByRole("button", { name: "Refuser" }).click()]);
  constat(G, "refuser-sans-effet", "refuser n'exécute rien (aucune ligne d'effet de plus)", lireEffets().length === avant + 1 && /rien n'a été exécuté/.test(await p.locator(".message").textContent()), lireEffets().length);
  // rejeu d'une décision déjà prise : on réutilise le formulaire de la dernière demande en double soumission
  await p.goto(B + "/approbations?statut=en_attente");
  const cible = await p.evaluate(() => { const f = [...document.querySelectorAll("article.carte")].find((c) => c.textContent.includes("Note fictive C du banc")).querySelector("form"); return { action: f.getAttribute("action"), csrf: f.querySelector("[name=csrf]").value }; });
  const envoi = () => ctx.request.post(new URL(cible.action, ORIGINE).href, { form: { csrf: cible.csrf, decision: "approuver", motif: "double" }, maxRedirects: 0 });
  const [da, db] = await Promise.all([envoi(), envoi()]);
  const doubles = [da.status(), db.status()];
  const apres = lireEffets();
  constat(G, "double-soumission", "double soumission simultanée d'une approbation : exécutée UNE seule fois", apres.length === avant + 2, { reponses: doubles, effets: apres.length });
  await p.goto(B + "/approbations");
  const restantes = await p.evaluate(() => document.querySelectorAll("article.carte form").length);
  constat(G, "file-restante", "après trois décisions, une seule demande reste en attente (la quatrième, jamais décidée)", restantes === 1, restantes);
  await ctx.close();
  // employé : refus d'accès
  const ctx2 = await nouveauContexte(br);
  const q = await ctx2.newPage();
  await q.goto(B + "/connexion");
  await q.fill("#identifiant", "employe-fictif"); await q.fill("#mot_de_passe", ids["employe-fictif"]);
  await Promise.all([q.waitForLoadState(), q.click("button[type=submit]")]);
  const rep = await q.goto(B + "/approbations");
  const texte = await q.evaluate(() => document.body.innerText);
  constat(G, "employe-refuse", "un employé ne voit pas la file : 403", rep.status() === 403 && !/m9_qualif/.test(texte), { statut: rep.status(), texte: texte.slice(0, 120) });
  constat(G, "refus-lisible", "le refus 403 d'une page est une page HTML lisible (titre, lien de retour), pas du JSON brut",
    /text\/html/.test(rep.headers()["content-type"] || "") && !/^\s*\{/.test(texte), { type: rep.headers()["content-type"], debut: texte.slice(0, 80) });
  await cap(q, "07-refus-employe");
  await ctx2.close();
}

async function g_plateforme(br) {
  const G = "plateforme";
  const ctx = await nouveauContexte(br);
  const p = await seConnecter(ctx, "proprio-fictif");
  await p.goto(B + "/plateforme/fournisseurs");
  const f = await p.evaluate(() => ({
    h1: document.querySelector("h1").textContent,
    lignes: document.querySelectorAll("table tbody tr").length,
    nav: [...document.querySelectorAll("main a")].filter((a) => /\/plateforme\//.test(a.getAttribute("href"))).map((a) => a.textContent),
    amesurer: /à mesurer/i.test(document.body.innerText), profilAbsent: /PROFIL_CLIENT_ABSENT/.test(document.body.innerText),
  }));
  constat(G, "fournisseurs", "registre de fournisseurs : tableau rempli, « à mesurer », profil client absent annoncé", f.lignes > 20 && f.amesurer && f.profilAbsent, f);
  await cap(p, "08-plateforme-fournisseurs");
  // Sous-navigation : chacune des cinq pages Plateforme expose les cinq sections (aucune impasse) et marque la page courante.
  const sections = ["fournisseurs", "secrets", "avatars", "connaissances", "connecteurs"];
  const impasses = [];
  for (const s of sections) {
    await p.goto(B + "/plateforme/" + s);
    const nav = await p.evaluate(() => { const n = document.querySelector('nav[aria-label="Plateforme"]'); return n ? { liens: [...n.querySelectorAll("a")].map((a) => a.getAttribute("href").split("/plateforme/")[1]), courant: [...n.querySelectorAll("a[aria-current=page]")].map((a) => a.getAttribute("href").split("/plateforme/")[1]) } : null; });
    if (!nav || JSON.stringify(nav.liens) !== JSON.stringify(sections) || JSON.stringify(nav.courant) !== JSON.stringify([s])) impasses.push(s + ": " + JSON.stringify(nav));
  }
  constat(G, "sous-navigation", "les cinq pages Plateforme portent la même navigation nommée (5 sections, page courante marquée) : aucune impasse", impasses.length === 0, impasses);
  await p.goto(B + "/plateforme/fournisseurs");
  // profil puis activation refusée avec son code
  await p.locator('input[name=usage_commercial]').check();
  await p.fill('input[name=revenu_annuel_usd]', "1500000");
  await p.locator('input[name=territoire_CA]').check();
  await Promise.all([p.waitForURL(/ok=profil/), p.locator('form[action$="/plateforme/fournisseurs/profil"] button').click()]);
  constat(G, "profil", "le profil de licence s'enregistre (bandeau de succès)", /Profil de licence enregistré/.test(await p.locator(".message").textContent()), null);
  // Sélecteurs de ligne : on cherche le formulaire « configurer » de tts.xtts-v2
  const formXtts = p.locator('form[action$="/plateforme/fournisseurs/configurer"]').filter({ has: p.locator('input[name=identifiant][value="tts.xtts-v2"]') });
  await formXtts.evaluate((f) => { const d = f.closest("details"); if (d) d.open = true; });
  await Promise.all([p.waitForURL(/ok=configure/), formXtts.locator("button").click()]);
  const formAct = p.locator('form[action$="/plateforme/fournisseurs/activer"]').filter({ has: p.locator('input[name=identifiant][value="tts.xtts-v2"]') });
  await formAct.evaluate((f) => { const d = f.closest("details"); if (d) d.open = true; });
  await Promise.all([p.waitForURL(/erreur=REFUS_POLITIQUE/), formAct.locator("button").click()]);
  const refus = await p.locator(".message").textContent();
  constat(G, "activation-refusee", "activer un fournisseur à licence non commerciale est refusé, code lisible, rien d'autre activé", /REFUS_POLITIQUE/.test(refus) && /LICENCE_NON_COMMERCIALE/.test(p.url()) && /Rien d.autre/.test(refus), refus);
  await cap(p, "09-plateforme-activation-refusee");

  // Secrets : saisie unique, masquage partout
  await p.goto(B + "/plateforme/secrets");
  const champ = await p.evaluate(() => document.querySelector('input[name=valeur]').type);
  constat(G, "secret-champ-masque", "le champ de valeur d'un secret est de type password", champ === "password", champ);
  await p.fill('form[action$="/secrets/definir"] input[name=nom]', "mistral.ocr");
  await p.selectOption('form[action$="/secrets/definir"] select[name=service]', "fournisseur_modele").catch(async () => { /* service par défaut */ });
  await p.fill('form[action$="/secrets/definir"] input[name=valeur]', SECRET_FICTIF);
  const [repS] = await Promise.all([p.waitForResponse((r) => r.request().method() === "POST" && /secrets\/definir/.test(r.url())), p.locator('form[action$="/secrets/definir"] button').click()]);
  await p.waitForLoadState();
  const html = await p.content();
  const loc = repS.headers()["location"] || "";
  const ligne = await p.locator("table tbody tr").first().textContent();
  constat(G, "secret-defini", "un secret saisi : bandeau « chiffré, ne sera plus affiché », une ligne de métadonnées, redirection sans la valeur",
    /Secret enregistré, chiffré/.test(await p.locator(".message").textContent()) && /mistral\.ocr/.test(ligne) && !loc.includes(SECRET_FICTIF), { loc, ligne: ligne.replace(/\s+/g, " ") });
  constat(G, "secret-jamais-reaffiche", "la valeur du secret n'apparaît ni dans le DOM, ni dans les champs, ni dans l'URL, ni dans le stockage du navigateur",
    !html.includes(SECRET_FICTIF) && !p.url().includes(SECRET_FICTIF) && (await p.evaluate((s) => JSON.stringify([localStorage, sessionStorage, document.cookie]).includes(s) || [...document.querySelectorAll("input,textarea")].some((i) => i.value === s), SECRET_FICTIF)) === false, null);
  await cap(p, "10-plateforme-secret-masque");
  await p.goto(B + "/api/plateforme/secrets");
  const api = await p.content();
  constat(G, "secret-api-masquee", "l'API JSON des secrets ne porte pas la valeur", !api.includes(SECRET_FICTIF) && /mistral\.ocr/.test(api), null);
  const rev = await p.request.get(B + "/api/plateforme/secrets/mistral.ocr/valeur");
  constat(G, "secret-valeur-fermee", "la lecture directe de la valeur d'un secret est refusée à la console (aucune route de lecture en clair)", rev.status() >= 400 && !(await rev.text()).includes(SECRET_FICTIF), rev.status());
  // Avatars, connaissances, connecteurs, observabilité
  const visites = [["plateforme/avatars", "Plateforme — avatars", "11-plateforme-avatars"], ["plateforme/connaissances", "Plateforme — connaissances", "12-plateforme-connaissances"],
    ["plateforme/connecteurs", "Plateforme — connecteurs", "13-plateforme-connecteurs"], ["connecteurs", "Connecteurs", null], ["observabilite", "Observabilité — coût et latence", "14-observabilite"]];
  for (const [chemin, titre, shot] of visites) {
    const r = await p.goto(B + "/" + chemin);
    const h1 = await p.locator("h1").textContent();
    const tables = await p.locator("table").count();
    constat(G, "page-" + chemin.replace("/", "-"), "page « " + titre + " » : 200, titre, contenu rendu", r.status() === 200 && h1 === titre, { statut: r.status(), h1, tables });
    if (shot) await cap(p, shot);
  }
  await p.goto(B + "/plateforme/avatars");
  const av = await p.evaluate(() => ({ lignes: document.querySelectorAll("table tbody tr").length, texte: document.querySelector("main").innerText.slice(0, 800) }));
  constat(G, "avatars-par-departement", "les avatars listent un département par ligne (10 réels + 1 fictif) avec voix/visage logiques", av.lignes >= 10, av);
  // révocation : le secret disparaît et la valeur reste introuvable
  await p.goto(B + "/plateforme/secrets");
  await p.locator('form[action$="/secrets/revoquer"] input[name=confirme]').check();
  await Promise.all([p.waitForURL(/ok=secret_revoque/), p.locator('form[action$="/secrets/revoquer"] button').click()]);
  constat(G, "secret-revoque", "révoquer un secret : confirmation explicite requise puis bandeau « octets chiffrés détruits »", /détruits/.test(await p.locator(".message").textContent()), null);
  constat(G, "reseau-externe-plateforme", "aucune requête hors 127.0.0.1 pendant le groupe", reseauExterne.length === 0, reseauExterne.slice(0, 5));
  const fuite = ctx.espion.corps.some((c) => c.includes(SECRET_FICTIF)) || ctx.espion.urls.some((u) => u.includes(SECRET_FICTIF)) || ctx.espion.locations.some((u) => u.includes(SECRET_FICTIF)) || ctx.espion.consoles.some((c) => c.includes(SECRET_FICTIF));
  constat(G, "secret-aucune-reponse", "la valeur du secret n'apparaît dans AUCUNE réponse, URL, redirection ni message de console reçus par le navigateur", !fuite, null);
  fs.writeFileSync(path.join(cfg.dossier, "secret-fictif.txt"), SECRET_FICTIF, { mode: 0o600 }); // relu par lancer.py pour fouiller journaux et base
  await ctx.close();
}

async function g_wallboards(br) {
  const G = "wallboards";
  const ctx = await nouveauContexte(br);
  fs.writeFileSync(cfg.horloge, cfg.horlogeFrais);
  const p = await seConnecter(ctx, "admin-fictif");
  await p.goto(B + "/wallboards");
  const ligne = await p.locator("tbody tr").count();
  const lien = await p.locator("tbody a").first().getAttribute("href");
  constat(G, "liste", "liste des wallboards : deux tableaux, lien de chaque ligne", ligne === 2 && /\/wallboards\//.test(lien), { ligne, lien });
  await p.goto(B + lien.replace("/opsys", ""));
  const etat1 = await p.evaluate(() => ({ banniere: document.getElementById("banniere").className, tuiles: [...document.querySelectorAll(".tuile")].map((t) => t.className), mise: document.getElementById("mise-a-jour").textContent }));
  constat(G, "rendu-initial", "rendu serveur initial sans JS : bannière et tuiles présentes", etat1.tuiles.length >= 6 && /banniere-/.test(etat1.banniere), etat1);
  await cap(p, "15-wallboard-frais");
  // SSE : la mention de connexion passe à « Connecté (flux) »
  await p.waitForFunction(() => /Connecté \(flux\)/.test(document.querySelector('[data-champ="connexion"]').textContent), null, { timeout: 12000 }).catch(() => {});
  const conn = await p.locator('[data-champ="connexion"]').textContent();
  constat(G, "flux-sse-ouvert", "le flux SSE s'ouvre (mention « Connecté (flux) »)", /Connecté \(flux\)/.test(conn), conn);
  const frais0 = await p.locator(".tuile.fraicheur-perime").count();
  // On fait vieillir l'horloge du serveur : les mesures deviennent périmées ; l'écran doit changer SANS recharger la page.
  const marque = await p.evaluate(() => { window.__marque = Math.random(); return window.__marque; });
  fs.writeFileSync(cfg.horloge, cfg.horlogePerime);
  await p.waitForFunction(() => document.querySelectorAll(".tuile.fraicheur-perime").length > 0, null, { timeout: 15000 }).catch(() => {});
  const apres = await p.evaluate(() => ({
    perimes: document.querySelectorAll(".tuile.fraicheur-perime").length, marque: window.__marque,
    banniere: document.getElementById("banniere").className, messages: document.querySelector('#banniere [data-champ="messages"]').innerText,
    textes: [...document.querySelectorAll(".tuile.fraicheur-perime [data-champ=etat]")].map((x) => x.textContent).slice(0, 2),
    mise: document.getElementById("mise-a-jour").textContent,
  }));
  constat(G, "sse-rafraichit", "le serveur pousse l'état « périmé » par SSE : tuiles périmées SANS rechargement (même document)", frais0 === 0 && apres.perimes > 0 && apres.marque === marque, { frais0, apres });
  constat(G, "perime-en-toutes-lettres", "une mesure périmée est écrite en toutes lettres et la bannière n'est plus « ok »", apres.textes.every((t) => /p[ée]rim[ée]e?/i.test(t)) && !/banniere-ok/.test(apres.banniere) && apres.messages.length > 0, apres);
  await cap(p, "16-wallboard-perime");
  // Pause : le bouton bascule aria-pressed et la mention de connexion
  await p.locator("#pause").click();
  const pause = await p.evaluate(() => ({ pressed: document.getElementById("pause").getAttribute("aria-pressed"), texte: document.getElementById("pause").textContent }));
  constat(G, "pause", "le bouton de pause bascule aria-pressed (WCAG 2.2.2)", pause.pressed === "true" && /Reprendre/.test(pause.texte), pause);
  fs.writeFileSync(cfg.horloge, cfg.horlogeFrais);
  await dormir(2500);
  const enPause = await p.locator(".tuile.fraicheur-perime").count();
  constat(G, "pause-fige", "en pause, l'écran ne se rafraîchit plus (les tuiles périmées restent affichées)", enPause > 0, enPause);
  await p.locator("#pause").click();
  await p.waitForFunction(() => document.querySelectorAll(".tuile.fraicheur-perime").length === 0, null, { timeout: 15000 }).catch(() => {});
  constat(G, "reprise-frais", "à la reprise, l'état revient à « à jour » par le flux", (await p.locator(".tuile.fraicheur-perime").count()) === 0, null);
  // Mode télé
  await Promise.all([p.waitForURL(/tv=1/), p.getByRole("link", { name: "Mode télé" }).click()]);
  constat(G, "mode-tele", "le mode télé s'affiche (classe tv, lien « Quitter »)", (await p.evaluate(() => document.body.className)) === "tv" && (await p.getByRole("link", { name: "Quitter le mode télé" }).count()) === 1, null);
  // Perte de connexion : le serveur coupé, la page doit le DIRE (horloge accélérée du navigateur : la vigie est à ~95 s)
  const page2 = await ctx.newPage();
  await page2.clock.install();
  await page2.goto(B + lien.replace("/opsys", ""));
  await page2.waitForFunction(() => /Connecté/.test(document.querySelector('[data-champ="connexion"]').textContent), null, { timeout: 12000 }).catch(() => {});
  await ctx.setOffline(true);
  await page2.clock.fastForward(130000);
  await dormir(800);
  const perdu = await page2.evaluate(() => ({ deconnectes: document.querySelectorAll(".tuile.deconnecte").length, conn: document.querySelector('[data-champ="connexion"]').textContent,
    banniere: document.querySelector('#banniere [data-champ="messages"]').innerText }));
  constat(G, "connexion-perdue", "réseau coupé : la page affiche « Connexion perdue », marque toutes les tuiles et dit de ne pas s'y fier", perdu.deconnectes >= 6 && /perdue/i.test(perdu.conn) && /Ne vous y fiez pas/.test(perdu.banniere), perdu);
  await cap(page2, "17-wallboard-connexion-perdue");
  await ctx.setOffline(false);
  await page2.close();
  await ctx.close();
  // Accès : le propriétaire seul n'est pas admin
  const ctx2 = await nouveauContexte(br);
  const q = await seConnecter(ctx2, "proprio-fictif");
  const r = await q.goto(B + "/wallboards");
  constat(G, "proprietaire-sans-role-admin", "le propriétaire sans rôle admin reçoit 403 sur les wallboards (page HTML lisible)", r.status() === 403 && /text\/html/.test(r.headers()["content-type"] || ""), { statut: r.status(), type: r.headers()["content-type"] });
  await ctx2.close();
  fs.writeFileSync(cfg.horloge, cfg.horlogeFrais);
}

async function g_agents_cron(br) {
  const G = "registre-cron";
  const ctx = await nouveauContexte(br);
  const p = await seConnecter(ctx, "proprio-fictif");
  await p.goto(B + "/agents");
  const valeurs = { id: "agent-qualif-navigateur", responsabilite: "Résumer fictivement les mesures du banc.", outils: "", budget_jour: "1000", budget_mois: "10000", limite_tours: "8", limite_reessais: "2", limite_concurrence: "1", declencheurs: "manuel\nhoraire 0 7 * * 1-5" };
  const form = p.locator('form[action$="/opsys/agents"]').first();
  for (const [k, v] of Object.entries(valeurs)) await form.locator('[name="' + k + '"]').fill(v);
  await form.locator('select[name=departement]').selectOption("m03-estimation");
  await Promise.all([p.waitForURL(/\/agents\/agent-qualif-navigateur$/), form.locator("button[type=submit]").click()]);
  const titre = await p.locator("h1").textContent();
  constat(G, "agent-cree", "un agent se crée par le formulaire (révision 1, inactif) et sa page de détail s'ouvre", /agent-qualif-navigateur|Agent|Configuration/.test(titre), titre);
  await Promise.all([p.waitForLoadState(), p.getByRole("button", { name: "Activer le profil" }).click()]);
  await p.waitForLoadState();
  constat(G, "agent-active", "le profil s'active (le bouton devient « Désactiver »)", (await p.getByRole("button", { name: "Désactiver le profil" }).count()) === 1, null);
  await cap(p, "18-agent-cron");
  const cron = p.locator('form[action$="/declencheurs/cron/demander"]');
  constat(G, "cron-formulaire", "le formulaire de demande cron est proposé (déclencheur horaire déclaré)", (await cron.count()) === 1, null);
  await cron.locator('input[name=fuseau]').fill("America/Toronto");
  // la case de confirmation est requise : sans elle, le navigateur bloque
  await cron.locator("button[type=submit]").click();
  await dormir(300);
  const bloque = await p.evaluate(() => document.querySelector('form[action$="/cron/demander"] input[name=confirme]').validationMessage);
  constat(G, "cron-confirmation-requise", "sans la case de confirmation, le navigateur refuse l'envoi", !!bloque && /demander/.test("demander") && !/Cron :/.test(await p.locator("main").innerText()), bloque);
  await cron.locator('input[name=confirme]').check();
  await Promise.all([p.waitForLoadState(), cron.locator("button[type=submit]").click()]);
  await p.waitForLoadState();
  const msg = await p.locator(".message").first().textContent();
  const style = await p.locator(".message").first().evaluate((m) => ({ fond: getComputedStyle(m).backgroundColor, classe: m.className }));
  constat(G, "message-succes-style", "le message de succès est stylé (fond visible, pas un paragraphe nu)", style.fond !== "rgba(0, 0, 0, 0)", style);
  constat(G, "cron-intention", "la demande cron est préparée INERTE : « Aucune tâche Core n'a été créée ou exécutée »", /Cron : demande préparée/.test(msg) && /Aucune tâche Core/.test(msg), msg);
  await cap(p, "19-cron-intention-preparee");
  await ctx.close();
}

async function g_deconnexion(br) {
  const G = "deconnexion";
  const ctx = await nouveauContexte(br);
  const p = await seConnecter(ctx, "proprio-fictif");
  const cookieAvant = (await ctx.cookies()).find((c) => c.name === "opsys_session").value;
  await Promise.all([p.waitForNavigation(), p.getByRole("button", { name: "Se déconnecter" }).click()]);
  await p.waitForLoadState();
  const restants = (await ctx.cookies()).filter((c) => c.name === "opsys_session");
  constat(G, "cookie-efface", "la déconnexion efface le cookie de session et renvoie à la connexion", restants.length === 0 && p.url().endsWith("/connexion"), { cookies: restants.length, url: p.url() });
  await p.goBack();
  await p.reload();
  constat(G, "retour-arriere", "retour arrière puis rechargement : page protégée refusée (redirigée vers la connexion), rien de mis en cache", p.url().endsWith("/connexion"), p.url());
  // Limite connue : session sans état côté serveur. Un cookie volé AVANT la déconnexion reste valable jusqu'à son échéance.
  const q = await ctx.newPage();
  await ctx.addCookies([{ name: "opsys_session", value: cookieAvant, url: B + "/", httpOnly: true, secure: true, sameSite: "Strict" }]);
  const r = await q.goto(B + "/departements");
  constat(G, "cookie-rejoue", "OBSERVÉ : un cookie copié avant la déconnexion est ENCORE accepté après (session sans état côté serveur, échéance 8 h) : limite à lever par une liste de révocation, hors périmètre de ce banc",
    true, { statut: r.status(), url: q.url(), accepte: r.status() === 200 }, "info");
  await ctx.close();
}

async function g_expiration(br) {
  const G = "expiration";
  const ctx = await nouveauContexte(br);
  const p = await seConnecter(ctx, "proprio-fictif", cfg.baseCourte);
  const c0 = (await ctx.cookies()).find((c) => c.name === "opsys_session");
  constat(G, "cookie-court", "instance à session courte : le cookie expire dans quelques secondes", c0 && c0.expires - Date.now() / 1000 <= cfg.dureeCourte + 2, c0 && Math.round(c0.expires - Date.now() / 1000));
  await dormir((cfg.dureeCourte + 2) * 1000);
  await p.goto(cfg.baseCourte + "/approbations");
  constat(G, "apres-echeance", "cookie périmé : la page protégée renvoie à la connexion", p.url().endsWith("/connexion"), p.url());
  await ctx.close();
  // Cookie signé valide mais DÉJÀ ÉCHU (le navigateur le renvoie : c'est le serveur qui le refuse) ; cookie falsifié.
  for (const [nom, valeur, attendu] of [["echu-signe", cfg.cookieEchu, "serveur"], ["falsifie", cfg.cookieFalsifie, "signature"]]) {
    const c2 = await nouveauContexte(br);
    await c2.addCookies([{ name: "opsys_session", value: valeur, url: B + "/", httpOnly: true, secure: true, sameSite: "Strict" }]);
    const q = await c2.newPage();
    const r = await q.goto(B + "/departements");
    const api = await q.request.get(B + "/api/session");
    constat(G, nom, "cookie " + nom + " : page renvoyée à la connexion et API en 401", q.url().endsWith("/connexion") && api.status() === 401, { url: q.url(), api: api.status(), refusePar: attendu });
    await c2.close();
  }
}

async function g_csrf(br) {
  const G = "csrf";
  const ctx = await nouveauContexte(br, { baseURL: undefined });
  const p = await seConnecter(ctx, "proprio-fictif");
  const csrf = await p.evaluate(() => document.querySelector("input[name=csrf]").value);
  const post = async (chemin, form) => { const r = await ctx.request.post(B + chemin, { form: form, maxRedirects: 0 }); return { s: r.status(), t: (await r.text()).slice(0, 300) }; };
  const put = async (entetes) => (await ctx.request.put(B + "/api/agents-plafonds", { data: { budget_jour: 1, budget_mois: 2, revision_attendue: 0 }, headers: entetes, maxRedirects: 0 })).status();
  const essais = {
    sansJeton: await post("/deconnexion", {}),
    jetonFaux: await post("/deconnexion", { csrf: "faux" }),
    decisionSansJeton: await post("/approbations/inconnue/decision", { decision: "approuver" }),
    plateformeSansJeton: await post("/plateforme/secrets/definir", { nom: "x.y", service: "google", valeur: SECRET_FICTIF }),
    apiSansJeton: await put({}),
    apiJetonFaux: await put({ "X-CSRF-Token": "faux" }),
  };
  constat(G, "post-sans-jeton", "POST /deconnexion sans jeton : 403, page « Action refusée », la session reste ouverte", essais.sansJeton.s === 403 && /Action refusée|jeton CSRF/.test(essais.sansJeton.t), essais.sansJeton);
  constat(G, "post-jeton-faux", "POST avec un jeton CSRF faux : 403", essais.jetonFaux.s === 403, essais.jetonFaux);
  constat(G, "decision-sans-jeton", "décision d'approbation sans jeton : 403", essais.decisionSansJeton.s === 403, essais.decisionSansJeton);
  constat(G, "secret-sans-jeton", "enregistrement d'un secret sans jeton : 403 et valeur non réécho", essais.plateformeSansJeton.s === 403 && !essais.plateformeSansJeton.t.includes(SECRET_FICTIF), essais.plateformeSansJeton.s);
  constat(G, "api-sans-jeton", "écriture de l'API JSON sans en-tête X-CSRF-Token : 403 (jeton faux aussi)", essais.apiSansJeton === 403 && essais.apiJetonFaux === 403, [essais.apiSansJeton, essais.apiJetonFaux]);
  const encore = await p.request.get(B + "/api/session");
  constat(G, "session-intacte", "après ces refus, la session reste valide et le jeton inchangé", encore.status() === 200 && (await encore.json()).csrf === csrf, encore.status());
  // Attaque inter-sites réelle : une page « attaquante » (autre site) soumet un formulaire vers la console.
  const attaquant = await ctx.newPage();
  const requetesVersConsole = [];
  attaquant.on("request", (r) => { if (r.url().startsWith(ORIGINE) && r.method() === "POST") requetesVersConsole.push(r); });
  await attaquant.route("http://attaquant.test/**", (route) => route.fulfill({ contentType: "text/html", body:
    '<!doctype html><title>x</title><form id="f" method="post" action="' + B + '/deconnexion"><input name="csrf" value="' + csrf + '"></form>' }));
  await attaquant.goto("http://attaquant.test/piege");
  await attaquant.evaluate(() => document.getElementById("f").submit());
  await attaquant.waitForLoadState();
  await dormir(500);
  const entetesEnvoyes = requetesVersConsole.length ? await requetesVersConsole[0].allHeaders() : {};
  const encore2 = await p.request.get(B + "/api/session");
  constat(G, "inter-sites-samesite", "formulaire soumis depuis un AUTRE SITE avec le bon jeton : le navigateur n'envoie PAS le cookie (SameSite=Strict) et la session survit",
    requetesVersConsole.length >= 1 && !("cookie" in entetesEnvoyes) && encore2.status() === 200, { posts: requetesVersConsole.length, cookieEnvoye: "cookie" in entetesEnvoyes, session: encore2.status(), urlFinale: attaquant.url() });
  await attaquant.close();
  await ctx.close();
}

async function g_entetes(br) {
  const G = "entetes-securite";
  const ctx = await nouveauContexte(br);
  const p = await seConnecter(ctx, "admin-fictif");
  const pagesVues = ["departements", "approbations", "budgets", "modeles", "agents", "plateforme/fournisseurs", "plateforme/secrets", "observabilite", "wallboards", "connexion"];
  const manques = [];
  for (const c of pagesVues) {
    const r = await p.goto(B + "/" + c);
    const h = r.headers();
    const attendu = { "content-security-policy": /default-src 'none'.*script-src 'self'.*frame-ancestors 'none'/, "x-content-type-options": /^nosniff$/, "x-frame-options": /^DENY$/, "referrer-policy": /^no-referrer$/, "cache-control": /no-store/ };
    for (const [k, re] of Object.entries(attendu)) if (!re.test(h[k] || "")) manques.push(c + ": " + k + "=" + (h[k] || "absent"));
  }
  constat(G, "pages", "10 pages : CSP stricte, nosniff, X-Frame-Options DENY, Referrer-Policy no-referrer, Cache-Control no-store", manques.length === 0, manques);
  const css = await p.request.get(B + "/statique/console.css");
  const h = css.headers();
  constat(G, "statique", "ressource statique : mêmes en-têtes de sécurité, cache public borné d'une heure", /nosniff/.test(h["x-content-type-options"] || "") && /max-age=3600/.test(h["cache-control"] || "") && /default-src 'none'/.test(h["content-security-policy"] || ""), h);
  const inconnue = await p.goto(B + "/chemin-inexistant");
  const texte = await p.evaluate(() => document.body.innerText);
  constat(G, "404-propre", "page inconnue : 404 sans trace d'exécution ni chemin de fichier", inconnue.status() === 404 && !/Traceback|\.py|File "/.test(texte), { statut: inconnue.status(), texte: texte.slice(0, 100) });
  const openapi = await p.request.get(B + "/openapi.json");
  const docs = await p.request.get(B + "/docs");
  constat(G, "pas-de-doc-api", "ni /docs ni /openapi.json (schéma non exposé)", openapi.status() === 404 && docs.status() === 404, [openapi.status(), docs.status()]);
  // CSP effective : une injection de script en ligne est BLOQUÉE par le navigateur lui-même.
  await p.goto(B + "/departements");
  await p.evaluate(() => { const s = document.createElement("script"); s.textContent = "window.__injecte = 1"; document.body.appendChild(s); });
  const injecte = await p.evaluate(() => window.__injecte === 1);
  await p.evaluate(() => { const i = document.createElement("img"); i.src = "https://exemple.invalide/pixel.png"; document.body.appendChild(i); });
  await dormir(300);
  constat(G, "csp-bloque-script-en-ligne", "la CSP bloque réellement un script injecté en ligne et une image externe (violation consignée par le navigateur)", injecte === false && ctx.espion.violationsCsp.length >= 1, { injecte, violations: ctx.espion.violationsCsp.length });
  const frame = await ctx.newPage();
  await frame.route("http://attaquant.test/**", (route) => route.fulfill({ contentType: "text/html", body: '<!doctype html><iframe id="i" src="' + B + '/connexion" width="400" height="300"></iframe>' }));
  await frame.goto("http://attaquant.test/cadre");
  await dormir(800);
  const cadre = frame.frames().find((f) => f.url().startsWith(ORIGINE));
  const bloque = !cadre || (await cadre.evaluate(() => document.body ? document.body.innerText : "").catch(() => "")) === "" || /refus|chrome-error/.test(cadre.url());
  constat(G, "anti-cadre", "la console ne s'affiche pas dans un cadre d'un autre site (frame-ancestors 'none' / X-Frame-Options)", bloque, cadre ? cadre.url() : "aucun cadre");
  const violationsReelles = ctx.espion.violationsCsp.filter((v) => !/exemple\.invalide|inline script|Executing inline script/.test(v));
  constat(G, "aucune-violation-csp-normale", "aucune violation de CSP sur le parcours normal des 10 pages (hors l'injection volontaire)", violationsReelles.length === 0, violationsReelles.slice(0, 3));
  await ctx.close();
}

async function g_a11y(br) {
  const G = "accessibilite";
  const pagesAdmin = ["departements", "approbations", "budgets", "modeles", "connecteurs", "agents", "memoire", "reception", "marketing", "finance", "fusion", "strategie",
    "plateforme/fournisseurs", "plateforme/secrets", "plateforme/avatars", "plateforme/connaissances", "plateforme/connecteurs", "observabilite", "wallboards"];
  const echecs = {}, balayees = new Set(), reflux = [], contrastes = {};
  for (const schema of ["light", "dark"]) {
    for (const w of [375, 768, 1280]) {
      const ctx = await nouveauContexte(br, { viewport: { width: w, height: 800 }, colorScheme: schema });
      const p = await seConnecter(ctx, "admin-fictif");
      const liste = pagesAdmin.slice();
      await p.goto(B + "/wallboards");
      const wb = await p.locator("tbody a").first().getAttribute("href");
      if (wb) liste.push(wb.replace("/opsys/", ""));
      liste.push("connexion");
      for (const c of liste) {
        const page = c === "connexion" ? await ctx.newPage() : p;
        if (c === "connexion") { await ctx.clearCookies(); }
        await page.goto(B + "/" + c);
        await page.evaluate(CONTROLES);
        const r = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, res: window.opsysControlesA11y(),
          cases: [...document.querySelectorAll("input[type=checkbox],input[type=radio]")].filter((i) => i.getBoundingClientRect().width > 40).length }));
        balayees.add(c);
        if (r.sw > r.cw) reflux.push(c + "@" + w + " (" + r.sw + ">" + r.cw + ")");
        if (r.cases) (echecs["cases-a-cocher-taille"] ||= new Set()).add(c + "@" + schema + "/" + w + ": " + r.cases + " case(s) étirée(s)");
        for (const x of r.res) {
          if (!x.ok && !/bonne pratique/.test(x.wcag)) (echecs[x.regle] ||= new Set()).add(c + "@" + schema + "/" + w + " " + JSON.stringify(x.details).slice(0, 160));
          if (x.regle === "contraste-texte") { const k = schema; contrastes[k] = Math.min(contrastes[k] || 99, (x.details.pire || {}).ratio || 99); }
        }
        if (c === "connexion") await page.close();
        if (c === "connexion") { /* on se reconnecte pour les pages suivantes du contexte */ }
      }
      await ctx.close();
    }
  }
  const regles = ["lang-fr", "titre-page", "un-seul-h1", "titres-sans-saut", "repere-main", "reperes-nav-nommes", "contenu-dans-reperes", "ids-uniques", "champs-etiquetes", "autocomplete-mot-de-passe",
    "boutons-nommes", "liens-nommes", "images-alt", "tables-entetes", "th-avec-scope", "pas-de-tabindex-positif", "erreurs-annoncees", "zoom-non-bloque", "references-aria-valides",
    "aucun-script-ni-style-en-ligne", "contraste-texte", "cases-a-cocher-taille"];
  for (const r of regles) constat(G, "regle-" + r, "règle « " + r + " » sur " + balayees.size + " pages × 3 largeurs × 2 thèmes", !echecs[r], echecs[r] ? [...echecs[r]].slice(0, 6) : null);
  constat(G, "reflow", "aucun défilement horizontal de la PAGE à 375, 768 et 1280 px (1.4.10) sur " + balayees.size + " pages", reflux.length === 0, reflux.slice(0, 12));
  constat(G, "contraste-min", "contraste minimal mesuré clair / sombre (texte)", true, contrastes, "info");
  // contraste de la pastille mesuré indépendamment (fond danger, texte blanc)
}

async function g_clavier(br) {
  const G = "clavier";
  const ctx = await nouveauContexte(br);
  const p = await ctx.newPage();
  await p.goto(B + "/connexion");
  await p.evaluate(CONTROLES);
  async function parcourir(page, max) {
    await page.evaluate(() => { document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0); });
    const pas = [];
    for (let i = 0; i < max; i++) {
      await page.keyboard.press("Tab");
      const f = await page.evaluate(() => window.opsysDecrireFocus());
      if (!f) break;
      pas.push(f);
      if (pas.length > 1 && f.el === pas[0].el && f.nom === pas[0].nom) { pas.pop(); break; }
    }
    return pas;
  }
  let pas = await parcourir(p, 10);
  const ordre = pas.map((x) => x.el);
  constat(G, "connexion-ordre", "connexion : Tab visite le lien d'évitement, l'identifiant, le mot de passe puis le bouton, dans cet ordre", ordre.length === 4 && ordre[0] === "a.saut" && ordre[1] === "input#identifiant" && ordre[2] === "input#mot_de_passe" && /^button/.test(ordre[3]), ordre);
  constat(G, "connexion-focus-visible", "connexion : chaque élément focalisé a un indicateur de focus visible (contour ou ombre)", pas.every((x) => x.visible), pas.filter((x) => !x.visible).map((x) => x.el));
  await p.keyboard.press("Shift+Tab");
  await p.fill("#identifiant", "proprio-fictif");
  await p.focus("#mot_de_passe");
  await p.keyboard.type(ids["proprio-fictif"]);
  await Promise.all([p.waitForURL(/\/departements$/), p.keyboard.press("Enter")]);
  constat(G, "connexion-entree", "la connexion se soumet au clavier (Entrée dans le champ mot de passe)", p.url().endsWith("/departements"), p.url());
  for (const [nom, chemin, max] of [["departements", "departements", 500], ["approbations", "approbations", 200], ["plateforme-secrets", "plateforme/secrets", 200], ["plateforme-fournisseurs", "plateforme/fournisseurs", 1500]]) {
    await p.goto(B + "/" + chemin);
    await p.evaluate(CONTROLES);
    const etapes = await parcourir(p, max);
    const sansFocus = etapes.filter((x) => !x.visible).map((x) => x.el + ":" + x.nom);
    const rangs = etapes.map((x) => x.rang);
    const croissant = rangs.every((r, i) => i === 0 || r >= rangs[i - 1]);
    const piege = etapes.length >= max;
    constat(G, nom + "-parcours", chemin + " : " + etapes.length + " arrêts de tabulation, ordre = ordre du document, aucun piège (retour au début atteint)", croissant && !piege && etapes.length > 5, { etapes: etapes.length, croissant, piege });
    constat(G, nom + "-focus", chemin + " : focus visible sur chaque arrêt, contraste du contour ≥ 3:1", sansFocus.length === 0 && etapes.every((x) => x.ratioFocus === null || x.ratioFocus >= 3), { sansFocus: sansFocus.slice(0, 8), minimum: Math.min(...etapes.map((x) => x.ratioFocus === null ? 99 : x.ratioFocus)) });
  }
  // Contournement des blocs (2.4.1) : lien d'évitement ou repères ; on mesure le coût au clavier pour atteindre le contenu.
  await p.goto(B + "/departements");
  await p.evaluate(CONTROLES);
  await p.evaluate(() => document.activeElement && document.activeElement.blur());
  await p.keyboard.press("Tab");
  const premier = await p.evaluate(() => window.opsysDecrireFocus());
  const saut = premier && /contenu|principal/i.test(premier.nom || "");
  constat(G, "lien-evitement", "un lien d'évitement (« Aller au contenu ») est le premier arrêt de tabulation", !!saut, premier);
  if (saut) {
    await p.keyboard.press("Enter");
    const apres = await p.evaluate(() => ({ hash: location.hash, actif: document.activeElement && document.activeElement.tagName }));
    await p.keyboard.press("Tab");
    const suite = await p.evaluate(() => window.opsysDecrireFocus());
    constat(G, "lien-evitement-effet", "activer le lien d'évitement amène le focus dans le contenu principal (le Tab suivant est dans <main>)", !!suite && suite.dansMain === true, { apres, suite });
  }
  // Boîte de confirmation (data-confirmer) atteignable et actionnable au clavier
  await p.goto(B + "/departements");
  const sel = p.locator("article.carte select").first();
  await sel.focus();
  await p.keyboard.press("ArrowDown");
  p.removeAllListeners("dialog");
  const dlg = [];
  p.once("dialog", async (d) => { dlg.push(d.message()); await d.dismiss(); });
  await p.keyboard.press("Tab");
  await p.keyboard.press("Enter");
  await dormir(400);
  constat(G, "confirmation-au-clavier", "changement de mode d'autonomie : sélection au clavier puis Entrée déclenche la confirmation, qu'on peut refuser", dlg.length === 1 && /mode d'autonomie/.test(dlg[0]), dlg);
  await ctx.close();
}

async function g_responsive(br) {
  const G = "responsive";
  const adm = ["departements", "approbations", "plateforme/secrets", "plateforme/fournisseurs", "finance", "budgets"];
  for (const w of [375, 768, 1280]) {
    const ctx = await nouveauContexte(br, { viewport: { width: w, height: 800 } });
    const p = await seConnecter(ctx, "admin-fictif");
    const defauts = [];
    for (const c of adm) {
      await p.goto(B + "/" + c);
      const m = await p.evaluate(() => {
        const sw = document.documentElement.scrollWidth, cw = document.documentElement.clientWidth;
        const hors = [...document.querySelectorAll("main *")].filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.right > cw + 1 && !e.closest(".table-defilante"); }).slice(0, 3).map((e) => e.tagName + "." + e.className);
        const nav = document.querySelector("nav[aria-label=Sections]").getBoundingClientRect();
        const entete = document.querySelector("header.entete").getBoundingClientRect().height;
        return { sw, cw, hors, navDebord: nav.right > cw + 1, entete: Math.round(entete) };
      });
      if (m.sw > m.cw || m.navDebord) defauts.push(c + ": " + JSON.stringify(m));
      if (w === 375 && m.entete > 400) defauts.push(c + ": en-tête de " + m.entete + " px sur un écran de 800 px (le contenu est repoussé hors de l'écran)");
      if (w === 375 && c === "departements") await cap(p, "22-mobile-375-departements");
      if (w === 375 && c === "finance") await cap(p, "23-mobile-375-finance");
      if (w === 768 && c === "plateforme-fournisseurs") await cap(p, "24-tablette-768");
    }
    constat(G, "largeur-" + w, "à " + w + " px : pas de défilement horizontal de la page, navigation dans l'écran (" + adm.length + " pages)", defauts.length === 0, defauts);
    await ctx.close();
  }
  const ctx = await nouveauContexte(br, { viewport: { width: 320, height: 800 } });
  const p = await seConnecter(ctx, "admin-fictif");
  const d = [];
  for (const c of ["departements", "approbations", "plateforme/secrets"]) { await p.goto(B + "/" + c); const m = await p.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]); if (m[0] > m[1]) d.push(c + " " + m.join(">")); }
  constat(G, "largeur-320", "à 320 px (équivalent d'un zoom 400 %, 1.4.10) : pas de défilement horizontal de la page", d.length === 0, d);
  await ctx.close();
}

async function g_journal(br) {
  const G = "journal";
  const ctx = await nouveauContexte(br);
  const p = await ctx.newPage();
  await p.goto(cfg.baseSansPrefixe + "/connexion");
  await p.fill("#identifiant", "intrus@example.test");
  await p.fill("#mot_de_passe", "mot-de-passe-faux-du-banc-journal");
  const [r] = await Promise.all([p.waitForResponse((x) => x.request().method() === "POST"), p.click("button[type=submit]")]);
  constat(G, "echec-sans-prefixe", "console servie sans préfixe (comme derrière Caddy) : un échec de connexion est refusé en 401 (la ligne d'accès est contrôlée contre le filtre fail2ban par lancer.py)", r.status() === 401, r.status());
  await ctx.close();
}

const TOUS = { connexion: g_connexion, tableau: g_tableau, approbations: g_approbations, plateforme: g_plateforme, wallboards: g_wallboards, cron: g_agents_cron, deconnexion: g_deconnexion,
  journal: g_journal, expiration: g_expiration, csrf: g_csrf, entetes: g_entetes, a11y: g_a11y, clavier: g_clavier, responsive: g_responsive };

(async () => {
  fs.mkdirSync(cfg.captures, { recursive: true });
  const br = await chromium.launch({ executablePath: cfg.chromium || undefined });
  const version = MOTEUR + " " + br.version();
  for (const [nom, fn] of Object.entries(TOUS)) {
    if (GROUPES && !GROUPES.has(nom)) continue;
    try { await fn(br); } catch (e) { constat(nom, "exception", "le groupe s'est terminé par une exception du banc", false, String(e && e.stack || e).slice(0, 600)); }
  }
  constat("global", "reseau-externe", "aucune requête n'a quitté 127.0.0.1 (le banc refuse tout le reste)", reseauExterne.length === 0, reseauExterne.slice(0, 5));
  constat("global", "captures", "taille totale des captures de cette exécution < 3 Mo", tailleCaptures < 3 * 1024 * 1024, tailleCaptures, "info");
  await br.close();
  fs.writeFileSync(cfg.resultats, JSON.stringify({ navigateur: version, horodatage: cfg.horodatage, captures_octets: tailleCaptures, constats: resultats }, null, 2));
  const echecs = resultats.filter((r) => !r.ok && r.niveau === "bloquant");
  console.log("\n" + resultats.length + " constats, " + echecs.length + " échec(s) bloquant(s), captures " + Math.round(tailleCaptures / 1024) + " Ko");
  process.exit(echecs.length ? 1 : 0);
})();
