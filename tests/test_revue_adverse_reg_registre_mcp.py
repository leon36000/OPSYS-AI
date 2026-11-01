"""Revue adverse (reg) : l'historique « qui a scellé quoi, quand » du registre MCP n'est pas modifiable sans la clé.

Le sceau HMAC ne couvrait que l'empreinte de la révision courante, `scelle_par` et `scelle_le`. Les fiches de
`historique` (qui a approuvé, quand, quels outils ajoutés, modifiés, retirés) n'étaient liées que par leurs champs
`precedent` et `empreinte_registre` : quiconque pouvait écrire le fichier, SANS la clé, réécrivait l'audit des
approbations et `depuis_dict` l'acceptait. Données fictives.
"""

from __future__ import annotations

import copy
import datetime as dt
import json

import pytest

from opsys.registre_mcp import registre as reg
from opsys.registre_mcp.registre import DefinitionOutil, RefusMCP

FICTIF = True
CLE = b"k" * 32
MAINTENANT = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC)
SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def _def(nom: str, description: str = "Fait quelque chose.", niveau: str = "N1") -> DefinitionOutil:
    return DefinitionOutil(nom, description, copy.deepcopy(SCHEMA), "m09-demo", niveau)


def _deux_revisions(cle: bytes | None = CLE) -> reg.Registre:
    r1 = reg.sceller([_def("m9_alpha")], None, par="alice", maintenant=MAINTENANT, cle=cle)
    return reg.sceller([_def("m9_alpha"), _def("m9_beta")], r1, par="bob",
                       maintenant=MAINTENANT + dt.timedelta(hours=1), cle=cle)


def _dict(registre: reg.Registre) -> dict:
    return json.loads(json.dumps(registre.vers_dict()))


@pytest.mark.parametrize("revision,champ,valeur", [
    (0, "par", "intrus"),
    (0, "ajoutes", ["m9_fantome"]),
    (0, "le", "2000-01-01T00:00:00Z"),
    (1, "par", "mallory"),
    (1, "ajoutes", []),
    (1, "retires", ["m9_gamma"]),
    (1, "niveaux_changes", ["m9_alpha"]),
])
def test_une_fiche_d_historique_falsifiee_est_refusee_avec_le_sceau_hmac(revision, champ, valeur):
    donnees = _dict(_deux_revisions())
    assert reg.depuis_dict(copy.deepcopy(donnees), cle=CLE)  # témoin : le fichier d'origine est accepté
    donnees["historique"][revision][champ] = valeur
    with pytest.raises(RefusMCP) as exc:
        reg.depuis_dict(donnees, cle=CLE)
    assert exc.value.code == "REJ-MCP-REGISTRE-ALTERE"


def test_la_derniere_fiche_doit_dire_la_meme_chose_que_le_sceau_meme_sans_cle():
    """Sceau sha256 (sans clé) : on peut resceller, mais une fiche incohérente avec le sceau reste une altération."""
    donnees = _dict(_deux_revisions(cle=None))
    assert reg.depuis_dict(copy.deepcopy(donnees))
    donnees["historique"][-1]["par"] = "mallory"  # scelle_par et le sceau disent toujours « bob »
    with pytest.raises(RefusMCP) as exc:
        reg.depuis_dict(donnees)
    assert exc.value.code == "REJ-MCP-REGISTRE-ALTERE"


@pytest.mark.parametrize("champ,valeur", [("par", "mallory"), ("le", "2000-01-01T00:00:00Z"), ("outils", 1)])
@pytest.mark.parametrize("avec_marque", [True, False], ids=["sceau-neuf", "sceau-ancien"])
def test_meme_resceller_a_la_main_une_fiche_finale_contredisant_la_revision_est_refuse(champ, valeur, avec_marque):
    """Sceau sha256 : l'éditeur recalcule marque ET sceau à la main. Reste le recoupement fiche finale / révision."""
    donnees = _dict(_deux_revisions(cle=None))
    donnees["historique"][-1][champ] = valeur
    donnees["sceau"] = reg._sceau(donnees["empreinte_registre"], donnees["revision"], donnees["scelle_par"],
                                  donnees["scelle_le"], None, donnees["historique"] if avec_marque else None)
    with pytest.raises(RefusMCP) as exc:
        reg.depuis_dict(donnees)
    assert exc.value.code == "REJ-MCP-REGISTRE-ALTERE"


def test_retirer_la_marque_d_historique_du_sceau_est_refuse():
    """Rétrograder un sceau neuf en sceau ancien (sans empreinte d'historique) casse le HMAC : refus, pas de repli."""
    donnees = _dict(_deux_revisions())
    assert "historique" in donnees["sceau"]
    del donnees["sceau"]["historique"]
    donnees["historique"][0]["par"] = "intrus"
    with pytest.raises(RefusMCP) as exc:
        reg.depuis_dict(donnees, cle=CLE)
    assert exc.value.code == "REJ-MCP-REGISTRE-SCEAU"


def test_ajouter_une_fiche_ou_en_retirer_une_est_refuse():
    donnees = _dict(_deux_revisions())
    faux = copy.deepcopy(donnees)
    faux["historique"].insert(0, {**faux["historique"][0], "revision": 0, "par": "fantome", "precedent": None})
    with pytest.raises(RefusMCP):
        reg.depuis_dict(faux, cle=CLE)


def test_un_ancien_registre_sans_empreinte_d_historique_reste_lisible():
    """Compatibilité : le registre livré (sha256 sans marque d'historique) et les HMAC d'avant restent acceptés."""
    r = _deux_revisions()
    donnees = _dict(r)
    ancien = copy.deepcopy(donnees)
    ancien["sceau"].pop("historique", None)
    ancien["sceau"]["valeur"] = reg._sceau(r.empreinte, r.revision, r.scelle_par, r.scelle_le, CLE)["valeur"]
    assert reg.depuis_dict(ancien, cle=CLE).revision == 2


def test_resceller_apres_un_ancien_sceau_pose_la_marque_d_historique():
    """Cas négatif : sceller une 3e révision sur un registre sain se vérifie, aller-retour fichier compris."""
    r2 = _deux_revisions()
    r3 = reg.sceller([_def("m9_alpha"), _def("m9_beta"), _def("m9_gamma")], r2, par="carol",
                     maintenant=MAINTENANT + dt.timedelta(hours=2), cle=CLE)
    relu = reg.depuis_dict(json.loads(reg.serialiser(r3)), cle=CLE)
    assert relu.revision == 3 and [h["par"] for h in relu.historique] == ["alice", "bob", "carol"]
