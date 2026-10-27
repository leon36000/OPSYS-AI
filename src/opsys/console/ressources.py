"""Feuille de style et script de la console, embarqués dans le paquet (aucun CDN, aucune police externe).

Servis par la console elle-même (`/statique/…`) : la politique de sécurité du contenu (CSP)
n'autorise que l'origine de la console.
"""

CSS = """\
:root {
  color-scheme: light dark;
  --fond: #f5f6f8; --surface: #ffffff; --texte: #1c2128; --attenue: #59636e; --bordure: #d1d9e0;
  --accent: #0a58ca; --accent-texte: #ffffff;
  --ok: #1a7f37; --ok-fond: #dafbe1; --alerte: #7d5200; --alerte-fond: #fff4d1;
  --danger: #c4212c; --danger-fond: #ffebe9; --rayon: 6px;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: 15px; line-height: 1.5;
}
@media (prefers-color-scheme: dark) {
  :root {
    --fond: #0f1318; --surface: #171c23; --texte: #e6edf3; --attenue: #9aa4af; --bordure: #2f3742;
    --accent: #5a9cf8; --accent-texte: #0f1318;
    --ok: #4ac26b; --ok-fond: #12301c; --alerte: #e3b341; --alerte-fond: #33280f;
    --danger: #ff7b72; --danger-fond: #3a1618;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--fond); color: var(--texte); }
a { color: var(--accent); }
.entete { display: flex; flex-wrap: wrap; align-items: center; gap: .75rem 1.5rem; padding: .75rem 1.5rem;
  background: var(--surface); border-bottom: 1px solid var(--bordure); }
.marque { font-weight: 700; letter-spacing: .02em; }
.marque span { font-weight: 400; color: var(--attenue); }
.entete nav { display: flex; flex-wrap: wrap; gap: .25rem; flex: 1; }
.entete nav a { padding: .35rem .75rem; border-radius: var(--rayon); color: var(--texte); text-decoration: none; }
.entete nav a:hover { background: var(--fond); }
.entete nav a[aria-current="page"] { background: var(--accent); color: var(--accent-texte); }
.pastille { display: inline-block; min-width: 1.4em; margin-left: .35em; padding: 0 .35em; border-radius: 999px;
  background: var(--danger); color: #ffffff; font-size: .8em; text-align: center; }
.session { display: flex; align-items: center; gap: .5rem; color: var(--attenue); font-size: .9em; }
main { max-width: 1200px; margin: 0 auto; padding: 1.5rem; }
h1 { margin: 0 0 1rem; font-size: 1.5rem; }
h2 { margin: 0; font-size: 1.1rem; }
h3, h4 { margin: 0; font-size: 1rem; }
section + section { margin-top: 2rem; }
section > h2 { margin-bottom: .75rem; }
.intro, .note { color: var(--attenue); }
.note { font-size: .9em; margin: 0; }
.vide { color: var(--attenue); font-style: italic; }
.grille { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); }
.carte { display: flex; flex-direction: column; gap: .75rem; padding: 1rem; background: var(--surface);
  border: 1px solid var(--bordure); border-radius: var(--rayon); }
.carte p { margin: 0; }
.carte-entete { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; }
.carte-entete h2, .carte-entete h3 { flex: 1; }
.code { font-weight: 700; color: var(--accent); }
.badge { display: inline-block; padding: .1rem .5rem; border: 1px solid var(--bordure); border-radius: 999px;
  font-size: .8em; white-space: nowrap; }
.badge-ok { background: var(--ok-fond); color: var(--ok); border-color: transparent; }
.badge-alerte { background: var(--alerte-fond); color: var(--alerte); border-color: transparent; }
.badge-danger { background: var(--danger-fond); color: var(--danger); border-color: transparent; }
.message { margin: 0 0 1rem; padding: .75rem 1rem; border-radius: var(--rayon); }
.message-ok { background: var(--ok-fond); color: var(--ok); }
.message-alerte { background: var(--alerte-fond); color: var(--alerte); }
.message-erreur { background: var(--danger-fond); color: var(--danger); }
table { width: 100%; border-collapse: collapse; font-size: .9em; }
th, td { padding: .4rem .5rem; border-bottom: 1px solid var(--bordure); text-align: left; vertical-align: top; }
th { color: var(--attenue); font-weight: 600; }
details summary { cursor: pointer; font-weight: 600; }
details[open] summary { margin-bottom: .5rem; }
code, pre { font-family: ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace; }
pre { margin: 0; padding: .75rem; overflow-x: auto; white-space: pre-wrap; word-break: break-word; font-size: .85em;
  background: var(--fond); border: 1px solid var(--bordure); border-radius: var(--rayon); }
dl.meta { display: grid; grid-template-columns: max-content 1fr; gap: .25rem .75rem; margin: 0; font-size: .9em; }
dl.meta dt { color: var(--attenue); }
dl.meta dd { margin: 0; }
ul.puces { display: flex; flex-wrap: wrap; gap: .35rem; margin: 0; padding: 0; list-style: none; }
form.ligne { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; }
form.pile { display: grid; gap: .5rem; }
label { font-size: .9em; font-weight: 600; }
input, select, textarea { width: 100%; padding: .4rem .5rem; font: inherit; color: var(--texte);
  background: var(--surface); border: 1px solid var(--bordure); border-radius: var(--rayon); }
form.ligne select { width: auto; }
button { padding: .4rem .9rem; font: inherit; cursor: pointer; color: var(--texte); background: var(--surface);
  border: 1px solid var(--bordure); border-radius: var(--rayon); }
button.principal { background: var(--accent); color: var(--accent-texte); border-color: var(--accent); }
button.danger { color: var(--danger); border-color: var(--danger); }
a:focus-visible, button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible,
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.actions { display: flex; flex-wrap: wrap; gap: .5rem; }
.filtres { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1rem; }
.filtres a { padding: .25rem .75rem; color: var(--texte); text-decoration: none; background: var(--surface);
  border: 1px solid var(--bordure); border-radius: 999px; }
.filtres a[aria-current="page"] { background: var(--accent); color: var(--accent-texte); border-color: var(--accent); }
.jauges { display: grid; gap: .5rem; }
.jauge { display: grid; gap: .25rem; }
.jauge-titre { display: flex; justify-content: space-between; gap: .5rem; font-size: .85em; }
.jauge-titre span { color: var(--attenue); }
meter { width: 100%; height: 1rem; }
.connexion { max-width: 380px; }
.cedule-navigation { display: flex; gap: .75rem; align-items: center; flex-wrap: wrap; }
.cedule-semaine { min-width: 1100px; table-layout: fixed; }
.cedule-semaine caption { text-align: left; padding: .5rem; color: var(--attenue); }
.cedule-semaine td { vertical-align: top; }
.cedule-semaine th { overflow-wrap: anywhere; }
.cedule-job { padding: .6rem; margin-bottom: .65rem; border: 1px solid var(--bordure);
  border-left: 4px solid var(--accent); border-radius: var(--rayon); background: var(--surface);
  overflow-wrap: anywhere; }
.cedule-job p { margin: .25rem 0; }
.cedule-job details { font-size: .8rem; }
.cedule-validite { font-size: .8rem; }
.cedule-perimee { border-left-color: var(--alerte); background: var(--alerte-fond); }
@media (max-width: 600px) { main { padding: 1rem; } .grille { grid-template-columns: 1fr; } }
"""

# Seul comportement côté navigateur : demander confirmation avant une action sensible.
JS = """\
"use strict";
document.addEventListener("submit", function (evenement) {
  var bouton = evenement.submitter;
  var message = (bouton && bouton.getAttribute("data-confirmer")) ||
    evenement.target.getAttribute("data-confirmer");
  if (message && !window.confirm(message)) {
    evenement.preventDefault();
  }
});
"""
