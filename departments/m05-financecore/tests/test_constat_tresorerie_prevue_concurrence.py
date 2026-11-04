"""C5 : le constat de trésorerie prévue protège son rang contre deux écritures simultanées.

`_constater_tresorerie_prevue` lit `rang = len(constats)` puis ajoute son maillon ; sans `rang_attendu=rang`, un
concurrent qui a inséré au même rang n'est jamais vu et deux maillons portent `sequence = 1`. Le registre durable sait
le dire (`EcritureConcurrente`) quand on lui passe le rang attendu, comme le fait déjà le constat du cash libre.
Données fictives, base SQLite temporaire (AGENTS.md).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import registre

from opsys import identite, stockage

FICTIF = True


def test_deux_constats_au_meme_rang_levent_ecriture_concurrente(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'concurrent.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(
        yaml.safe_dump(
            {
                "configuration": {
                    "fiscal": {
                        "frequence_tps_tvq": "trimestrielle",
                        "mois_fin_exercice": 12,
                        "taxes_remises_jusqu_au": "2026-06-30",
                    },
                    "obligations_declarees": {
                        "paies": {"montant": "0.00", "source": "fictif", "au": "2026-09-25"},
                        "das": {"montant": "0.00", "source": "fictif", "au": "2026-09-25"},
                        "dettes": {"montant": "0.00", "source": "fictif", "au": "2026-09-25"},
                    },
                    "prevision": {
                        "horizon_semaines": 2,
                        "seuil_alerte": {"montant": "1000.00", "source": "fictif", "au": "2026-09-25"},
                        "delai_encaissement_clients_jours": 30,
                        "delai_paiement_fournisseurs_jours": 30,
                        "echeances_obligations": {
                            "paies": "2026-10-09",
                            "das": "2026-10-15",
                            "dettes": "2026-10-31",
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin", "mot-de-passe-admin-12345", ["admin"])
        reg = m5_outils._registre_mouvements(None)
        registre.enregistrer_mouvement(
            {
                "montant": Decimal("5000.00"),
                "type_mouvement": "ENCAISSEMENT",
                "horodatage": "2026-09-01T12:00:00-04:00",
                "classe_retention": "STANDARD",
                "source": "fictif",
            },
            reg,
        )

    # Simule une écriture concurrente survenue entre `rang = len(constats)` et `constats.append(...)`.
    vrai_maillons = stockage.maillons

    class MaillonsAvecConcurrent:
        def __init__(self, inner):
            self._inner = inner

        def __len__(self):
            return len(self._inner)

        def __getitem__(self, item):
            return self._inner[item]

        def append(self, maillon, *, rang_attendu=None):
            # Un concurrent a inséré un maillon au rang 0 juste avant notre append.
            self._inner.append(
                {
                    "type_entree": "tresorerie_prevue_constatee",
                    "sequence": 1,
                    "date_reference": "2026-09-28",
                    "version_donnees": "a" * 64,
                    "statut_alerte": "AUCUNE",
                    "evenement_id": "m5-tresorerie-prevue-1-2026-09-28-aaaaaaaaaaaaaaaa",
                }
            )
            return self._inner.append(maillon, rang_attendu=rang_attendu)

    def faux_maillons(dep, nom="principal"):
        maillons = vrai_maillons(dep, nom)
        if nom == "constats_tresorerie_prevue":
            return MaillonsAvecConcurrent(maillons)
        return maillons

    with patch.object(stockage, "maillons", side_effect=faux_maillons):
        try:
            with pytest.raises(stockage.EcritureConcurrente), stockage.transaction():
                m5_outils._constater_tresorerie_prevue(
                    m5_outils._registre_mouvements(None), date(2026, 9, 29), "2026-09-29T07:00:00-04:00"
                )
        finally:
            stockage.liberer()

    # La transaction perdante est annulée : aucun constat du jour ne survit, donc pas de doublon de sequence 1.
    with stockage.transaction():
        traces = list(stockage.maillons("m05-financecore", "constats_tresorerie_prevue"))
    assert all(trace.get("date_reference") != "2026-09-29" for trace in traces)
