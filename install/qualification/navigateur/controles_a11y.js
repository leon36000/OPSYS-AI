/* Contrôles d'accessibilité (WCAG 2.1 AA) injectés dans la page par le banc navigateur.
 *
 * axe-core n'est pas disponible hors ligne : ces contrôles sont NOS PROPRES règles, volontairement limitées à ce qui se
 * mesure de façon fiable dans le DOM. Ils NE COUVRENT PAS : la qualité des textes alternatifs, la logique de lecture
 * réelle d'un lecteur d'écran, le sens des libellés, les médias, les animations/clignotements, les gestes tactiles,
 * le contraste des images de fond, des dégradés et des pseudo-éléments, l'espacement du texte (1.4.12), le zoom 200 %
 * (1.4.4), l'orientation. Voir QUALIFICATION-NAVIGATEUR.md, rubrique « NON PROUVÉ ».
 *
 * Chaque contrôle rend { regle, wcag, ok, details } ; la fonction globale `opsysControlesA11y()` rend la liste.
 */
(function () {
  "use strict";

  function nomAccessible(el) {
    var lab = el.getAttribute("aria-labelledby");
    if (lab) {
      var t = lab.split(/\s+/).map(function (id) { var x = document.getElementById(id); return x ? x.textContent : ""; }).join(" ").trim();
      if (t) return t;
    }
    var a = (el.getAttribute("aria-label") || "").trim();
    if (a) return a;
    if (el.labels && el.labels.length) {
      var l = Array.prototype.map.call(el.labels, function (x) { return x.textContent; }).join(" ").trim();
      if (l) return l;
    }
    if (el.tagName === "INPUT" && /^(submit|button|reset)$/.test(el.type)) return (el.value || "").trim();
    var ti = (el.getAttribute("title") || "").trim();
    if (ti) return ti;
    return (el.textContent || "").trim();
  }

  function visible(el) {
    var r = el.getBoundingClientRect();
    var s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none" && (r.width > 0 || r.height > 0);
  }

  function chemin(el) {
    var p = el.tagName.toLowerCase();
    if (el.id) p += "#" + el.id;
    else if (el.getAttribute("name")) p += "[name=" + el.getAttribute("name") + "]";
    else if (el.className && typeof el.className === "string") p += "." + el.className.trim().split(/\s+/)[0];
    return p;
  }

  // -- contraste --------------------------------------------------------------------------------------------------
  function analyser(c) {
    var m = /rgba?\(([^)]+)\)/.exec(c);
    if (!m) return null;
    var v = m[1].split(/[ ,/]+/).filter(Boolean).map(parseFloat);
    return { r: v[0], g: v[1], b: v[2], a: v.length > 3 ? v[3] : 1 };
  }
  function melange(dessus, dessous) {
    var a = dessus.a;
    return { r: dessus.r * a + dessous.r * (1 - a), g: dessus.g * a + dessous.g * (1 - a), b: dessus.b * a + dessous.b * (1 - a), a: 1 };
  }
  function lum(c) {
    var f = function (x) { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  }
  function ratio(a, b) {
    var la = lum(a), lb = lum(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  }
  // Couleur de fond effective : on remonte les ancêtres en composant les fonds translucides ; le canevas est le fond du body/html.
  function fondEffectif(el) {
    var pile = [];
    for (var n = el; n; n = n.parentElement) {
      var bg = analyser(getComputedStyle(n).backgroundColor);
      if (bg && bg.a > 0) pile.push(bg);
      if (bg && bg.a === 1) break;
    }
    var base = { r: 255, g: 255, b: 255, a: 1 };
    var cs = analyser(getComputedStyle(document.documentElement).backgroundColor);
    if (cs && cs.a > 0) base = melange(cs, base);
    for (var i = pile.length - 1; i >= 0; i--) base = melange(pile[i], base);
    return base;
  }

  function contrastes() {
    var echecs = [], mesures = 0, pire = null;
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    var vus = new Set();
    var n;
    while ((n = walker.nextNode())) {
      if (!n.nodeValue.trim()) continue;
      var el = n.parentElement;
      if (!el || vus.has(el) || !visible(el)) continue;
      vus.add(el);
      var tag = el.tagName;
      if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT" || el.closest("[hidden]")) continue;
      var s = getComputedStyle(el);
      var fg = analyser(s.color);
      if (!fg) continue;
      var bg = fondEffectif(el);
      var fgOpaque = melange(fg, bg);
      var r = ratio(fgOpaque, bg);
      var px = parseFloat(s.fontSize), gras = parseInt(s.fontWeight, 10) >= 700;
      var grand = px >= 24 || (px >= 18.66 && gras);
      var seuil = grand ? 3 : 4.5;
      var desactive = el.closest(":disabled, [aria-disabled=true]");
      if (desactive) continue; // WCAG 1.4.3 exempte les composants inactifs
      mesures++;
      if (!pire || r < pire.ratio) pire = { ratio: Math.round(r * 100) / 100, el: chemin(el) };
      if (r < seuil) echecs.push({ el: chemin(el), texte: n.nodeValue.trim().slice(0, 40), ratio: Math.round(r * 100) / 100, seuil: seuil });
    }
    return { echecs: echecs, mesures: mesures, pire: pire };
  }

  // -- contrôles ---------------------------------------------------------------------------------------------------
  window.opsysControlesA11y = function () {
    var res = [];
    function regle(id, wcag, ok, details) { res.push({ regle: id, wcag: wcag, ok: !!ok, details: details || [] }); }

    var lang = document.documentElement.getAttribute("lang") || "";
    regle("lang-fr", "3.1.1", /^fr(-[A-Za-z]+)?$/.test(lang), lang || "absent");
    regle("titre-page", "2.4.2", (document.title || "").trim().length > 0, document.title);
    var h1 = document.querySelectorAll("h1");
    regle("un-seul-h1", "1.3.1", h1.length === 1, h1.length);
    var niveaux = Array.prototype.map.call(document.querySelectorAll("h1,h2,h3,h4,h5,h6"), function (h) { return +h.tagName[1]; });
    var saut = [];
    for (var i = 1; i < niveaux.length; i++) if (niveaux[i] - niveaux[i - 1] > 1) saut.push(niveaux[i - 1] + "→" + niveaux[i]);
    regle("titres-sans-saut", "1.3.1", saut.length === 0, saut);

    regle("repere-main", "1.3.1/2.4.1", document.querySelectorAll("main, [role=main]").length === 1,
      document.querySelectorAll("main, [role=main]").length);
    var nav = document.querySelectorAll("nav, [role=navigation]");
    var navSansNom = Array.prototype.filter.call(nav, function (x) { return nav.length > 1 && !x.getAttribute("aria-label") && !x.getAttribute("aria-labelledby"); }).map(chemin);
    regle("reperes-nav-nommes", "1.3.1", navSansNom.length === 0, navSansNom);
    var hors = Array.prototype.filter.call(document.body.children, function (x) {
      return !/^(HEADER|MAIN|NAV|FOOTER|ASIDE|SCRIPT|NOSCRIPT|STYLE|A)$/.test(x.tagName) && !x.matches("[role]");
    }).map(chemin);
    regle("contenu-dans-reperes", "1.3.1", hors.length === 0, hors);

    var ids = {}, dup = [];
    Array.prototype.forEach.call(document.querySelectorAll("[id]"), function (x) { if (ids[x.id]) dup.push(x.id); ids[x.id] = 1; });
    regle("ids-uniques", "4.1.1", dup.length === 0, dup);

    var champs = Array.prototype.filter.call(document.querySelectorAll("input, select, textarea"), function (x) {
      return x.type !== "hidden" && !/^(submit|button|reset|image)$/.test(x.type);
    });
    var sansEtiquette = champs.filter(function (x) { return !nomAccessible(x); }).map(chemin);
    regle("champs-etiquetes", "1.3.1/3.3.2/4.1.2", sansEtiquette.length === 0, sansEtiquette);
    var autocompl = champs.filter(function (x) { return x.type === "password" && !x.getAttribute("autocomplete"); }).map(chemin);
    regle("autocomplete-mot-de-passe", "1.3.5", autocompl.length === 0, autocompl);

    var boutons = Array.prototype.filter.call(document.querySelectorAll("button, [role=button], input[type=submit], input[type=button]"), visible);
    var bSans = boutons.filter(function (x) { return !nomAccessible(x); }).map(chemin);
    regle("boutons-nommes", "4.1.2", bSans.length === 0, bSans);
    var liens = Array.prototype.filter.call(document.querySelectorAll("a[href]"), visible);
    var lSans = liens.filter(function (x) { return !nomAccessible(x); }).map(chemin);
    regle("liens-nommes", "2.4.4/4.1.2", lSans.length === 0, lSans);
    var imgs = Array.prototype.filter.call(document.querySelectorAll("img"), function (x) { return !x.hasAttribute("alt"); }).map(chemin);
    regle("images-alt", "1.1.1", imgs.length === 0, imgs);

    var tables = Array.prototype.filter.call(document.querySelectorAll("table"), visible);
    var tSans = tables.filter(function (t) {
      if (t.getAttribute("role") === "presentation" || t.getAttribute("role") === "none") return false;
      var ths = t.querySelectorAll("th");
      if (!ths.length) return true;
      var vides = Array.prototype.filter.call(ths, function (th) { return !(th.textContent || "").trim() && !th.getAttribute("aria-label"); });
      return vides.length > 0;
    }).map(chemin);
    regle("tables-entetes", "1.3.1", tSans.length === 0, tSans);
    var thSansScope = [];
    tables.forEach(function (t) {
      Array.prototype.forEach.call(t.querySelectorAll("th"), function (th) {
        if (!th.getAttribute("scope") && !th.id && !th.closest("thead")) thSansScope.push(chemin(t) + " > th:" + (th.textContent || "").trim().slice(0, 20));
      });
    });
    regle("th-avec-scope", "1.3.1 (th du corps du tableau)", thSansScope.length === 0, thSansScope.slice(0, 12));
    var tLegende = tables.filter(function (t) { return !t.querySelector("caption") && !t.getAttribute("aria-label") && !t.getAttribute("aria-labelledby"); }).map(chemin);
    regle("tables-nommees", "1.3.1 (bonne pratique)", tLegende.length === 0, tLegende);

    var tabindex = Array.prototype.filter.call(document.querySelectorAll("[tabindex]"), function (x) { return +x.getAttribute("tabindex") > 0; }).map(chemin);
    regle("pas-de-tabindex-positif", "2.4.3", tabindex.length === 0, tabindex);

    var live = document.querySelectorAll("[role=alert], [role=status], [aria-live]");
    var erreurs = document.querySelectorAll(".message-erreur");
    var erreursNonAnnoncees = Array.prototype.filter.call(erreurs, function (x) { return !(x.getAttribute("role") === "alert" || x.closest("[role=alert]") || x.getAttribute("aria-live") === "assertive"); }).map(chemin);
    regle("erreurs-annoncees", "3.3.1/4.1.3", erreursNonAnnoncees.length === 0, erreursNonAnnoncees);

    var meta = document.querySelector("meta[name=viewport]");
    var vp = meta ? meta.getAttribute("content") || "" : "";
    regle("zoom-non-bloque", "1.4.4", !/user-scalable\s*=\s*(no|0)/i.test(vp) && !/maximum-scale\s*=\s*1(\.0)?\b/i.test(vp), vp);

    var ariaCasse = [];
    Array.prototype.forEach.call(document.querySelectorAll("[aria-labelledby],[aria-describedby]"), function (x) {
      ["aria-labelledby", "aria-describedby"].forEach(function (a) {
        (x.getAttribute(a) || "").split(/\s+/).filter(Boolean).forEach(function (id) { if (!document.getElementById(id)) ariaCasse.push(chemin(x) + " " + a + "=" + id); });
      });
    });
    regle("references-aria-valides", "4.1.2", ariaCasse.length === 0, ariaCasse);

    var inlineScript = Array.prototype.filter.call(document.querySelectorAll("script:not([src])"), function (x) { return x.type !== "application/json"; }).length;
    var inlineStyle = document.querySelectorAll("[style], style").length;
    regle("aucun-script-ni-style-en-ligne", "(CSP)", inlineScript === 0 && inlineStyle === 0, { scripts: inlineScript, styles: inlineStyle });

    var c = contrastes();
    regle("contraste-texte", "1.4.3", c.echecs.length === 0, { mesures: c.mesures, pire: c.pire, echecs: c.echecs.slice(0, 15) });

    return res;
  };

  // Ordre de tabulation et focus visible : exécutés depuis le banc (les touches viennent de Playwright). Ce petit utilitaire
  // décrit l'élément qui a le focus et dit si son indicateur de focus se distingue (contour ou ombre non nuls).
  window.opsysDecrireFocus = function () {
    var el = document.activeElement;
    if (!el || el === document.body) return null;
    var s = getComputedStyle(el), r = el.getBoundingClientRect();
    var contour = s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 1;
    var ombre = s.boxShadow && s.boxShadow !== "none";
    var focalisables = Array.prototype.filter.call(document.querySelectorAll(
      'a[href],button:not([disabled]),input:not([type=hidden]):not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])'), visible);
    var ratioFocus = null;
    if (contour) {
      var couleur = analyser(s.outlineColor);
      if (couleur) { var fond = fondEffectif(parseFloat(s.outlineOffset) > 0 && el.parentElement ? el.parentElement : el); ratioFocus = Math.round(ratio(melange(couleur, fond), fond) * 100) / 100; }
    }
    return { el: chemin(el), nom: nomAccessible(el).slice(0, 40), rang: focalisables.indexOf(el), top: Math.round(r.top + window.scrollY), left: Math.round(r.left),
      contour: contour, ombre: !!ombre, visible: contour || !!ombre, ratioFocus: ratioFocus, dansMain: !!el.closest("main"),
      dansViewport: r.bottom > 0 && r.top < window.innerHeight, hauteur: Math.round(r.height), largeur: Math.round(r.width) };
  };
})();
