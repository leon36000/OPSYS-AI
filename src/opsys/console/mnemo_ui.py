"""Console « Plateforme > Mnémo » : modèle de soi, graphe de connaissances et leçons, en LECTURE seule.

Aucune écriture, aucun formulaire : confirmer un énoncé ou une arête sensible, déclarer une règle de la direction et
décider d'une leçon passent par les outils M10 (niveau N3, une personne, journalisés) ; cette page dit ce qui ATTEND
une décision. Rien de ce que la page rend n'est un texte libre d'un tiers : les libellés d'énoncés sont écrits par le
code, un client ou une propriété ne s'affiche que par un pseudonyme court (Loi 25). Session obligatoire, rôle
d'administration relu avant ET après la lecture (même règle que la Plateforme), `Cache-Control: no-store`.

Routes : /plateforme/mnemo (page) ; /api/plateforme/mnemo (JSON).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..mnemo import lecture
from ..mnemo.codes import ErreurMnemo
from . import pages
from .securite import Session

ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}
ONGLET = "plateforme/fournisseurs"
_STATUTS = {
    "confirme": ("confirmé", "badge-ok"),
    "a_confirmer": ("à confirmer", "badge-alerte"),
    "inconnu": ("inconnu", "badge-danger"),
}
_LIMITE_CONTRADICTIONS = 10
_ID_CONTRADICTION = re.compile(r"^[0-9a-f]{32}$")
_STATUTS_CONTRADICTION = {
    "ouverte": "À examiner",
    "en_attente_humain": "À valider par une personne",
}
_MARQUES_CONTRADICTION = frozenset({"valide", "retenue", "dominee", "contestee"})


def _badge(texte: str, classe: str) -> str:
    return f'<span class="badge {pages.e(classe)}">{pages.e(texte)}</span>'


def _soi(vue: Mapping[str, Any]) -> str:
    e = pages.e
    lignes = []
    for c in vue["couverture"]:
        libelle, classe = _STATUTS[c["statut"]]
        lignes.append(
            f"<tr><td><code>{e(c['dimension'])}</code>{' · structurante' if c['structurante'] else ''}</td>"
            f"<td>{_badge(libelle, classe)}</td><td>{int(c['confirmes'])}</td><td>{int(c['proposes'])}</td>"
            f"<td>{int(c['revisions_en_attente'])}</td><td>{int(c['derives_ouvertes'])}</td>"
            f"<td>{e(c['alimentation'])}</td></tr>"
        )
    couverture = (
        "<table><thead><tr><th>Dimension</th><th>Statut</th><th>Confirmés</th><th>Proposés</th>"
        "<th>Révisions à trancher</th><th>Dérives ouvertes</th><th>Alimentation</th></tr></thead>"
        f"<tbody>{''.join(lignes)}</tbody></table>"
    )
    confirmes = "".join(
        f"<li>{e(x['libelle'])} <small>(confiance {e(x['niveau_confiance'])} {e(x['confiance'])} · "
        f"{int(x['age_jours'])} j"
        f" · confirmé par {e(x['confirme_par'])})</small></li>"
        for x in vue["enonces"]
        if x["etat"] == "confirme"
    )
    revisions = "".join(
        f"<li><strong>{e(x['dimension'])}</strong> : proposé « {e(x['libelle'])} » à la place de « "
        f"{e(x.get('revise_libelle', '—'))} » <small>(énoncé {e(x['enonce_id'])})</small></li>"
        for x in vue["revisions_en_attente"]
    )
    derives = "".join(
        f"<li><code>{e(d['dimension'])}</code> / <code>{e(d['cle'])}</code> : la source ne le soutient plus "
        f"(depuis {e(d['depuis'][:10])})</li>"
        for d in vue["derives_ouvertes"]
    )
    propose = sum(1 for x in vue["enonces"] if x["etat"] == "propose" and not x["revise"])
    return (
        "<section><h2>Modèle de soi de l'entreprise</h2>"
        f'<p class="note">{e(vue["avertissement"])}</p>{couverture}'
        f"<h3>Énoncés confirmés</h3><ul>{confirmes or '<li>aucun</li>'}</ul>"
        f"<h3>Révisions à trancher par la direction</h3><ul>{revisions or '<li>aucune</li>'}</ul>"
        f"<h3>Sources disparues (dérive)</h3><ul>{derives or '<li>aucune</li>'}</ul>"
        f"<p>{propose} énoncé(s) proposé(s) attendent une première confirmation.</p></section>"
    )


def _graphe(g: Mapping[str, Any]) -> str:
    e = pages.e
    noeuds = ", ".join(f"{e(t)} {int(n)}" for t, n in g["noeuds_par_type"].items())
    etats = ", ".join(f"{e(t)} {int(n)}" for t, n in g["aretes_par_etat"].items())
    attente = "".join(
        f"<tr><td><code>{e(a['arete_id'][:12])}</code></td><td>{e(a['type'])}</td><td>{e(a['de'])} → "
        f"{e(a['vers'])}</td>"
        f"<td>{e(a['valide_de'])}</td><td>{e(a['source'])}</td><td>{'oui' if a['sensible'] else 'non'}</td></tr>"
        for a in g["en_attente"]
    )
    tableau = (
        "<table><thead><tr><th>Arête</th><th>Type</th><th>Relation</th><th>Depuis</th><th>Source</th>"
        f"<th>Sensible</th></tr></thead><tbody>{attente}</tbody></table>"
        if attente
        else "<p>Aucune.</p>"
    )
    return (
        "<section><h2>Graphe de connaissances</h2>"
        f"<p>Nœuds : {noeuds}. Arêtes : {etats}. Moteur : {e(g['moteur'])}. Un client ou une propriété ne s'affiche "
        f"que par un "
        "pseudonyme court.</p>"
        f"<h3>En attente de la confirmation d'une personne ({int(g['aretes_sensibles_en_attente'])} "
        f"sensible(s))</h3>{tableau}"
        "</section>"
    )


def _lecons(v: Mapping[str, Any]) -> str:
    e = pages.e
    lignes = []
    for lc in v["lecons"]:
        ev = lc["evaluation"]
        mesure = ev["mesure"]
        if mesure is None:
            texte_mesure = "non faite"
        elif not mesure["mesurable"]:
            texte_mesure = "non mesurable hors ligne"
        else:
            texte_mesure = f"erreur {e(mesure['erreur_avant'])} → {e(mesure['erreur_apres'])}"
        garde = ev["garde_gabarit"]
        texte_garde = "non lancée" if garde is None else f"{len(garde.get('regressions', ()))} régression(s)"
        decisions = ", ".join(f"{e(d['etape'])} ({e(d['par'])})" for d in lc["decisions"]) or "—"
        lignes.append(
            f"<tr><td>{e(lc['genre'])}</td><td><code>{e(lc['cible'])}</code></td><td>{e(lc['libelle'])}</td>"
            f"<td>{_badge(lc['etat'], 'badge-ok' if lc['etat'] == 'complete' else 'badge-alerte')}</td>"
            f"<td>{texte_mesure}</td><td>{texte_garde}</td><td>{decisions}</td></tr>"
        )
    tableau = (
        "<table><thead><tr><th>Genre</th><th>Visé</th><th>Leçon</th><th>État</th><th>Mesure hors ligne</th>"
        f"<th>Garde du gabarit</th><th>Décisions humaines</th></tr></thead><tbody>{''.join(lignes)}</tbody></table>"
        if lignes
        else "<p>Aucune leçon.</p>"
    )
    canari = "aucun" if v["canari"] is None else f"{int(v['canari'][1])} % ({e(v['canari'][0])})"
    return (
        f'<section><h2>Leçons apprises</h2><p class="note">{e(v["avertissement"])}</p>'
        f"<p>Promues : {len(v['actives'])} · canari en cours : {canari}.</p>{tableau}</section>"
    )


def _resume_contradiction(item: Any, classes: frozenset[str]) -> dict[str, Any] | None:
    """Projection fermée : aucun sujet, valeur, émetteur, motif ou référence ne quitte le lecteur M10."""
    if not isinstance(item, Mapping):
        return None
    identifiant = item.get("contradiction_id")
    statut = item.get("statut")
    if not isinstance(identifiant, str) or not _ID_CONTRADICTION.fullmatch(identifiant):
        return None
    if not isinstance(statut, str) or statut not in _STATUTS_CONTRADICTION:
        return None
    marques = item.get("marques")
    if not isinstance(marques, Mapping):
        marques = {}

    sources = []
    for cote in ("a", "b"):
        source = item.get(cote)
        if not isinstance(source, Mapping):
            return None
        classe = source.get("classe")
        ligne_id = source.get("ligne_id")
        marque = marques.get(ligne_id) if isinstance(ligne_id, str) else None
        sources.append({
            "classe": classe if isinstance(classe, str) and classe in classes else "inconnue",
            "marque": marque if isinstance(marque, str) and marque in _MARQUES_CONTRADICTION else "inconnue",
        })

    proposition = item.get("proposition")
    retenue = proposition.get("retenue") if isinstance(proposition, Mapping) else None
    demande = item.get("demande")
    return {
        "identifiant": identifiant[:12],
        "statut": statut,
        "critique": item.get("critique") is True,
        "source_a": sources[0],
        "source_b": sources[1],
        "proposition": retenue if retenue in ("a", "b") else None,
        "demande_en_attente": isinstance(demande, Mapping) and demande.get("statut") == "en_attente",
    }


def _lire_contradictions_admin() -> dict[str, dict[str, Any]]:
    """Lit les deux files M10 séparément; l'appelant garde la session admin avant et après cette lecture."""
    domaines_attendus = ("affaires", "developpement")

    def indisponible() -> dict[str, Any]:
        return {
            "statut": "indisponible",
            "total": 0,
            "limite": _LIMITE_CONTRADICTIONS,
            "affichees": 0,
            "plus": False,
            "elements": [],
        }

    try:
        from m10_memoire import contradictions_outils, verite

        classes = frozenset(x for x in verite.charger().classes if isinstance(x, str))
        domaines = verite.domaines()
    except Exception:
        return {domaine: indisponible() for domaine in domaines_attendus}

    resultats: dict[str, dict[str, Any]] = {}
    for domaine in domaines:
        if domaine not in domaines_attendus:
            continue
        try:
            lecture = contradictions_outils.lire_contradictions(
                domaine,
                vue="contradictions",
                etat="a_traiter",
                limite=_LIMITE_CONTRADICTIONS,
                decalage=0,
            )
        except Exception:
            resultats[domaine] = indisponible()
            continue
        if not isinstance(lecture, Mapping) or lecture.get("accepte") is not True:
            resultats[domaine] = indisponible()
            continue
        resultat = lecture.get("resultat")
        if not isinstance(resultat, Mapping):
            resultats[domaine] = indisponible()
            continue
        brutes = resultat.get("contradictions")
        elements = []
        if isinstance(brutes, list):
            for item in brutes[:_LIMITE_CONTRADICTIONS]:
                resume = _resume_contradiction(item, classes)
                if resume is not None:
                    elements.append(resume)
        total = resultat.get("total")
        total = min(total, 2_147_483_647) if type(total) is int and total >= 0 else len(elements)
        suivant = resultat.get("suivant")
        omis_budget = resultat.get("omis_budget")
        resultats[domaine] = {
            "statut": "disponible",
            "total": total,
            "limite": _LIMITE_CONTRADICTIONS,
            "affichees": len(elements),
            "plus": total > len(elements)
            or (type(suivant) is int and suivant >= 0)
            or (type(omis_budget) is int and omis_budget > 0),
            "elements": elements,
        }
    return resultats


def _contradictions(vues: Mapping[str, Mapping[str, Any]]) -> str:
    e = pages.e
    noms = {"affaires": "Mémoire d’affaires", "developpement": "Mémoire de développement"}
    sections = []
    for domaine in ("affaires", "developpement"):
        vue = vues.get(domaine, {})
        if vue.get("statut") != "disponible":
            sections.append(f"<section><h3>{noms[domaine]}</h3><p>File indisponible.</p></section>")
            continue
        total = vue.get("total", 0)
        affichees = vue.get("affichees", 0)
        lignes = []
        for item in vue.get("elements", []):
            proposition = {"a": "Source A", "b": "Source B"}.get(item["proposition"], "À trancher")
            demande = "Demande N3 en attente" if item["demande_en_attente"] else "Aucune demande N3"
            lignes.append(
                "<tr>"
                f"<td><code>{e(item['identifiant'])}</code></td>"
                f"<td>{e(_STATUTS_CONTRADICTION[item['statut']])}</td>"
                f"<td>{'oui' if item['critique'] else 'non'}</td>"
                f"<td>{e(item['source_a']['classe'])} · {e(item['source_a']['marque'])}</td>"
                f"<td>{e(item['source_b']['classe'])} · {e(item['source_b']['marque'])}</td>"
                f"<td>{e(proposition)}</td><td>{e(demande)}</td></tr>"
            )
        tableau = (
            "<table><thead><tr><th>ID</th><th>État</th><th>Critique</th><th>Source A</th><th>Source B</th>"
            f"<th>Proposition</th><th>Sas humain</th></tr></thead><tbody>{''.join(lignes)}</tbody></table>"
            if lignes
            else "<p>Aucune contradiction à traiter.</p>"
        )
        suite = " · d’autres résultats sont omis" if vue.get("plus") else ""
        sections.append(
            f"<section><h3>{noms[domaine]}</h3><p>{e(affichees)} affichée(s) sur {e(total)} · "
            f"maximum {e(vue.get('limite', _LIMITE_CONTRADICTIONS))}{suite}</p>{tableau}</section>"
        )
    return (
        '<section><h2>Contradictions à traiter</h2>'
        '<p class="note">Lecture seule, séparée par domaine. '
        'Les valeurs et références des affirmations ne sont pas affichées. '
        "Toute décision reste dans le sas humain N3.</p>"
        f"{''.join(sections)}</section>"
    )


def contenu(vue: Mapping[str, Any], *, prefixe: str) -> str:
    e = pages.e
    return (
        pages.navigation_plateforme(prefixe, "mnemo") +
        '<p class="note">Lecture seule. Confirmer, rejeter, retirer, déclarer ou décider se fait par les outils M10 '
        f"(niveau N3, une personne, journalisé). {e(vue['mention_professionnelle'])}. Aucun modèle de langage n'a "
        f"produit "
        "ces énoncés : ils viennent de lectures existantes et de décisions de la direction.</p>"
        + _soi(vue["soi"])
        + _graphe(vue["graphe"])
        + _contradictions(vue["contradictions"])
        + _lecons(vue["lecons"])
    )


def creer_router(
    *,
    session_page: Callable[..., Session],
    session_api: Callable[..., Session],
    cnx_factory: Callable[[], Any],
    prefixe: str,
) -> APIRouter:
    router = APIRouter(tags=["mnemo"])

    def lire() -> dict[str, Any]:
        with cnx_factory() as cnx:
            vue = lecture.vue_admin(cnx)
            vue["contradictions"] = _lire_contradictions_admin()
            return vue

    @router.get("/plateforme/mnemo", response_class=HTMLResponse)
    def page_mnemo(request: Request) -> Response:
        session = session_page(request)
        try:
            corps = contenu(lire(), prefixe=prefixe)
        except ErreurMnemo:
            corps = "<p>Mnémo ne peut pas être lu.</p>"
        session_page(request)
        return HTMLResponse(
            pages.gabarit("Plateforme — Mnémo", corps, prefixe=prefixe, session=session, actif=ONGLET), headers=ENTETES
        )

    @router.get("/api/plateforme/mnemo")
    def api_mnemo(request: Request) -> Response:
        session_api(request)
        vue = lire()
        session_api(request)
        return JSONResponse(vue, headers=ENTETES)

    return router
