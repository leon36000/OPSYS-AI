const { creer } = require(process.argv[2]);
class Classes { constructor() { this.s = new Set(); }
  add(c) { this.s.add(c); } remove(c) { this.s.delete(c); } contains(c) { return this.s.has(c); } }
class El {
  constructor(tag, attrs = {}, dataset = {}) { this.tag = tag; this.attrs = attrs; this.dataset = dataset; this.enfants = [];
    this.classList = new Classes(); this.ecouteurs = {}; this._texte = ""; }
  set innerHTML(v) { throw new Error("innerHTML interdit"); }
  get textContent() { return this._texte + this.enfants.map((e) => e.textContent).join(""); }
  set textContent(v) { this._texte = String(v); this.enfants = []; }
  get firstChild() { return this.enfants[0] || null; }
  removeChild(c) { this.enfants = this.enfants.filter((e) => e !== c); }
  appendChild(c) { this.enfants.push(c); }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(t, f) { this.ecouteurs[t] = f; }
  *tous() { yield this; for (const e of this.enfants) yield* e.tous(); }
  querySelector(sel) { const m = /\[data-champ="([a-z-]+)"\]/.exec(sel); for (const e of this.tous()) { if (m && e.attrs["data-champ"] === m[1]) return e; } return null; }
}
function construire() {
  const racine = new El("main", {}, { intervalle: "30", api: "/api/wb", flux: "/api/wb/flux" });
  const mk = (champs) => { const t = new El("li"); champs.forEach((c) => { const e = new El("p", { "data-champ": c }); t.enfants.push(e); }); return t; };
  const t1 = mk(["valeur", "etat", "detail"]); t1.attrs["data-tuile"] = "leads"; t1.classList.add("tuile");
  const t2 = mk(["valeur", "etat", "detail"]); t2.attrs["data-tuile"] = "carnet"; t2.classList.add("tuile");
  const banniere = new El("div", { id: "banniere" }); banniere.enfants.push(new El("div", { "data-champ": "messages" }));
  const maj = new El("p", { id: "mise-a-jour" });
  const pause = new El("button", { id: "pause" });
  racine.enfants.push(new El("span", { "data-champ": "connexion" }), t1, t2);
  const doc = {
    getElementById: (id) => id === "wallboard" ? racine : id === "banniere" ? banniere : id === "mise-a-jour" ? maj : id === "pause" ? pause : null,
    querySelector: (sel) => { const m = /\[data-tuile="([a-z0-9-]*)"\]/.exec(sel); return [t1, t2].find((t) => t.attrs["data-tuile"] === (m && m[1])) || null; },
    querySelectorAll: (sel) => sel === ".tuile" ? [t1, t2] : [],
    createElement: (tag) => new El(tag),
  };
  return { doc, racine, t1, t2, banniere, maj, pause };
}
function donnees(extra = {}) {
  return { maintenant: "2026-10-30T20:00:00-04:00", banniere: { niveau: "ok", messages: ["Tout est à jour."] },
    tuiles: [{ id: "leads", valeur_affichee: "20 leads", libelle_fraicheur: "À jour", libelle_seuil: "sans seuil", age_affiche: "2 h 05 min", etat_seuil: "sans_seuil", fraicheur: "a_jour" },
             { id: "carnet", valeur_affichee: "25 000,00 $", libelle_fraicheur: "PÉRIMÉE", libelle_seuil: "seuil non évalué", age_affiche: null, etat_seuil: "indetermine", fraicheur: "perime" }], ...extra };
}
class FauxFlux { static instances = []; constructor(url, opts) { this.url = url; this.opts = opts; this.ecouteurs = {}; this.ferme = false; FauxFlux.instances.push(this); }
  addEventListener(t, f) { this.ecouteurs[t] = f; } close() { this.ferme = true; } }
function env(dom, options = {}) {
  const minuteries = []; let maintenant = 1000000;
  const e = { document: dom.doc, EventSource: options.sansFlux ? undefined : FauxFlux,
    fetch: options.fetch || (() => Promise.resolve({ ok: true, json: () => Promise.resolve(donnees()) })),
    setTimeout: (f, d) => { minuteries.push({ f, d }); return minuteries.length; }, clearTimeout: () => {},
    setInterval: (f, d) => { minuteries.push({ f, d, intervalle: true }); return minuteries.length; },
    maintenant: () => maintenant };
  return { e, minuteries, avancer: (ms) => { maintenant += ms; } };
}
const sortie = {};
async function principal() {
  // 1. appliquer : textContent seulement, aucune injection
  { const dom = construire(); const { e } = env(dom); const app = creer(e);
    const hostile = donnees(); hostile.tuiles[0].valeur_affichee = "<img src=x onerror=alert(1)>"; hostile.banniere.messages = ["<script>x</script>"];
    app.appliquer(hostile);
    sortie.texte_hostile = dom.t1.querySelector('[data-champ="valeur"]').textContent;
    sortie.banniere_enfants = dom.banniere.enfants[0].enfants.map((x) => [x.tag, x.textContent]);
    sortie.detail = dom.t1.querySelector('[data-champ="detail"]').textContent;
    sortie.classes_t2 = [...dom.t2.classList.s].sort();
    sortie.maj = dom.maj.textContent; }
  // 1b. une tuile à couverture partielle le dit ; la mise à jour suivante, complète, n'en garde aucune trace
  { const dom = construire(); const { e } = env(dom); const app = creer(e);
    const partiel = donnees(); partiel.tuiles[0].partielle = true; app.appliquer(partiel);
    sortie.etat_partielle = dom.t1.querySelector('[data-champ="etat"]').textContent;
    sortie.etat_complete = dom.t2.querySelector('[data-champ="etat"]').textContent;
    app.appliquer(donnees());
    sortie.etat_apres_complet = dom.t1.querySelector('[data-champ="etat"]').textContent; }
  // 2. flux : ouverture, instantané, fin -> fermeture et reconnexion planifiée
  { FauxFlux.instances.length = 0; const dom = construire(); const { e, minuteries } = env(dom); const app = creer(e); app.demarrer();
    const flux = FauxFlux.instances[0]; sortie.flux_url = flux.url; sortie.flux_credentials = flux.opts.withCredentials;
    flux.ecouteurs.instantane({ data: JSON.stringify(donnees()) });
    sortie.apres_instantane = dom.t1.querySelector('[data-champ="valeur"]').textContent;
    sortie.connexion = dom.racine.querySelector('[data-champ="connexion"]').textContent;
    flux.ecouteurs.fin({}); sortie.flux_ferme_apres_fin = flux.ferme; sortie.reconnexion_planifiee = minuteries.some((m) => m.d === 1000);
    flux.ecouteurs.instantane({ data: "pas du json" }); /* ne doit pas lever */ }
  // 3. repli : pas d'EventSource -> interrogation à l'intervalle
  { const dom = construire(); const { e, minuteries } = env(dom, { sansFlux: true }); const app = creer(e); app.demarrer();
    const t = minuteries.find((m) => m.d === 30000); sortie.repli_planifie = Boolean(t);
    t.f(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); await new Promise((r) => setImmediate(r));
    sortie.repli_valeur = dom.t1.querySelector('[data-champ="valeur"]').textContent; }
  // 4. perte de connexion dite
  { const dom = construire(); const { e, avancer } = env(dom, { fetch: () => Promise.reject(new Error("réseau")) }); const app = creer(e);
    app.surveiller(); sortie.avant_perte = dom.t1.classList.contains("deconnecte");
    avancer(30000 * 3 + 6000); app.surveiller();
    sortie.apres_perte = dom.t1.classList.contains("deconnecte") && dom.t2.classList.contains("deconnecte");
    sortie.banniere_perte = dom.banniere.enfants[0].enfants.map((x) => x.textContent);
    sortie.statut_connexion = dom.racine.querySelector('[data-champ="connexion"]').textContent;
    app.appliquer(donnees()); sortie.retablie = !dom.t1.classList.contains("deconnecte"); }
  // 5. pause : coupe flux et minuteries, bascule aria-pressed, reprise rouvre
  { FauxFlux.instances.length = 0; const dom = construire(); const { e, avancer } = env(dom); const app = creer(e); app.demarrer();
    const flux = FauxFlux.instances[0]; app.basculerPause();
    sortie.pause_flux_ferme = flux.ferme; sortie.pause_aria = dom.pause.attrs["aria-pressed"]; sortie.pause_texte = dom.pause.textContent;
    avancer(10 * 3600 * 1000); app.surveiller(); sortie.pause_sans_alarme = !dom.t1.classList.contains("deconnecte");
    app.basculerPause(); sortie.reprise_aria = dom.pause.attrs["aria-pressed"]; sortie.reprise_nouveau_flux = FauxFlux.instances.length === 2; }
  // 6. un identifiant de tuile hostile ne trouve rien et ne lève pas
  { const dom = construire(); const { e } = env(dom); const app = creer(e); const d = donnees(); d.tuiles[0].id = "leads\"] , body [x=\""; app.appliquer(d); sortie.id_hostile_ok = true; }
  console.log(JSON.stringify(sortie));
}
principal().catch((err) => { console.log(JSON.stringify({ erreur: String(err && err.stack || err) })); process.exit(1); });
