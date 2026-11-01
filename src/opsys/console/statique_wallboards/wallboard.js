(function (global) {
  "use strict";
  var CLASSES_ETAT = ["etat-normal", "etat-attention", "etat-critique", "etat-indetermine", "etat-sans_seuil"];
  var CLASSES_FRAICHEUR = ["fraicheur-a_jour", "fraicheur-perime", "fraicheur-inconnu", "fraicheur-manquant",
    "fraicheur-non_applicable"];
  var CLASSES_BANNIERE = ["banniere-ok", "banniere-attention", "banniere-critique"];
  var DELAI_RECONNEXION_MS = 5000;
  var TOLERANCE_PERTE = 3;

  function creer(env) {
    var doc = env.document;
    var racine = doc.getElementById("wallboard");
    var etat = { pause: false, dernierSucces: env.maintenant(), source: null, minuterie: null, vigie: null, page: 0,
      rotation: null, fluxOuvert: false };
    var intervalleMs = Math.max(5, parseInt(racine.dataset.intervalle, 10) || 30) * 1000;

    function champ(parent, nom) { return parent.querySelector('[data-champ="' + nom + '"]'); }
    function remplacerClasse(el, anciennes, nouvelle) {
      anciennes.forEach(function (c) { el.classList.remove(c); });
      el.classList.add(nouvelle);
    }
    function appliquerTuile(t) {
      var el = doc.querySelector('[data-tuile="' + String(t.id).replace(/[^a-z0-9-]/g, "") + '"]');
      if (!el) { return; }
      champ(el, "valeur").textContent = String(t.valeur_affichee);
      champ(el, "etat").textContent = String(t.libelle_fraicheur) + " · " + String(t.libelle_seuil) +
        (t.partielle === true ? " · couverture partielle" : "");
      champ(el, "detail").textContent = t.age_affiche ? "Dernier fait il y a " + String(t.age_affiche) : "Aucun âge connu";
      remplacerClasse(el, CLASSES_ETAT, "etat-" + String(t.etat_seuil));
      remplacerClasse(el, CLASSES_FRAICHEUR, "fraicheur-" + String(t.fraicheur));
      el.classList.remove("deconnecte");
    }
    function appliquerBanniere(b) {
      var el = doc.getElementById("banniere");
      remplacerClasse(el, CLASSES_BANNIERE, "banniere-" + String(b.niveau));
      var zone = champ(el, "messages");
      while (zone.firstChild) { zone.removeChild(zone.firstChild); }
      b.messages.forEach(function (m) {
        var p = doc.createElement("p");
        p.textContent = String(m);
        zone.appendChild(p);
      });
    }
    function appliquer(donnees) {
      donnees.tuiles.forEach(appliquerTuile);
      appliquerBanniere(donnees.banniere);
      doc.getElementById("mise-a-jour").textContent = "Mis à jour : " + String(donnees.maintenant);
      etat.dernierSucces = env.maintenant();
    }
    function marquerDeconnecte() {
      doc.querySelectorAll(".tuile").forEach(function (el) { el.classList.add("deconnecte"); });
      var el = doc.getElementById("banniere");
      remplacerClasse(el, CLASSES_BANNIERE, "banniere-attention");
      var zone = champ(el, "messages");
      while (zone.firstChild) { zone.removeChild(zone.firstChild); }
      var p = doc.createElement("p");
      p.textContent = "Connexion perdue : les valeurs affichées ne sont plus rafraîchies. Ne vous y fiez pas.";
      zone.appendChild(p);
      champ(doc.getElementById("wallboard"), "connexion").textContent = "Connexion perdue";
    }
    function surveiller() {
      if (!etat.pause && env.maintenant() - etat.dernierSucces > TOLERANCE_PERTE * intervalleMs + 5000) {
        marquerDeconnecte();
      }
    }
    function interroger() {
      if (etat.pause) { return Promise.resolve(); }
      return env.fetch(racine.dataset.api, { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) { if (!r.ok) { throw new Error("statut " + r.status); } return r.json(); })
        .then(function (d) { appliquer(d); champ(racine, "connexion").textContent = "Connecté"; })
        .catch(function () { /* la vigie dira la perte de connexion */ });
    }
    function planifierInterrogation() {
      etat.minuterie = env.setTimeout(function () {
        interroger().then(function () { if (!etat.fluxOuvert) { planifierInterrogation(); } });
      }, intervalleMs);
    }
    function ouvrirFlux() {
      if (!env.EventSource || etat.pause) { planifierInterrogation(); return; }
      var source = new env.EventSource(racine.dataset.flux, { withCredentials: true });
      etat.source = source;
      etat.fluxOuvert = true;
      source.addEventListener("instantane", function (e) {
        try { appliquer(JSON.parse(e.data)); champ(racine, "connexion").textContent = "Connecté (flux)"; } catch (err) { /* ignoré */ }
      });
      source.addEventListener("fin", function () {
        source.close(); etat.fluxOuvert = false; etat.source = null;
        if (!etat.pause) { etat.minuterie = env.setTimeout(ouvrirFlux, 1000); }
      });
      source.onerror = function () {
        source.close(); etat.fluxOuvert = false; etat.source = null;
        if (!etat.pause) { interroger(); etat.minuterie = env.setTimeout(ouvrirFlux, DELAI_RECONNEXION_MS); }
      };
    }
    function arreter() {
      if (etat.source) { etat.source.close(); etat.source = null; }
      etat.fluxOuvert = false;
      if (etat.minuterie !== null) { env.clearTimeout(etat.minuterie); etat.minuterie = null; }
    }
    function basculerPause() {
      etat.pause = !etat.pause;
      var bouton = doc.getElementById("pause");
      bouton.setAttribute("aria-pressed", etat.pause ? "true" : "false");
      bouton.textContent = etat.pause ? "Reprendre le rafraîchissement" : "Mettre en pause";
      if (etat.pause) { arreter(); } else { etat.dernierSucces = env.maintenant(); ouvrirFlux(); }
    }
    function demarrer() {
      var bouton = doc.getElementById("pause");
      if (bouton) { bouton.addEventListener("click", basculerPause); }
      etat.vigie = env.setInterval(surveiller, Math.max(1000, intervalleMs / 2));
      ouvrirFlux();
    }
    return { demarrer: demarrer, appliquer: appliquer, basculerPause: basculerPause, surveiller: surveiller,
      etat: etat, interroger: interroger, arreter: arreter };
  }

  if (typeof module !== "undefined" && module.exports) { module.exports = { creer: creer }; }
  if (typeof document !== "undefined" && document.getElementById("wallboard")) {
    creer({ document: document, fetch: global.fetch.bind(global), EventSource: global.EventSource,
      setTimeout: global.setTimeout.bind(global), clearTimeout: global.clearTimeout.bind(global),
      setInterval: global.setInterval.bind(global), maintenant: function () { return Date.now(); } }).demarrer();
  }
})(typeof window !== "undefined" ? window : globalThis);
