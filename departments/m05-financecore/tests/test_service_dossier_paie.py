"""Service du dossier de paie préparatoire sur une vraie base SQLite : versions, CAS, rejeu, revue, export (fictif)."""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from m5_financecore import dossier_paie_preparatoire as d
from m5_financecore import export_paie_preparatoire as export
from m5_financecore import journal_dossiers_paie as journal
from m5_financecore import service_dossier_paie as service
from sqlalchemy import select, text

from opsys import stockage
from opsys.stockage.schema import REGISTRES

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures_dossier_paie import ADMISSION_OK, ADMISSION_REFUSEE, copie, entrees  # noqa: E402

FICTIF = True
EMPLOYE = "employe-fictif-un"
AUTRE_EMPLOYE = "employe-fictif-deux"
OWNER = "proprietaire-fictif"
NOW = "2026-10-28T12:00:00+00:00"
LIENS = ({"id": "webras", "url": "https://exemple.invalide/webras", "usage": "calcul humain"},)


class Sources:
    """Fournisseurs injectés : mêmes formes que `preparer_brut_regulier` et l'admission serveur, données fictives."""

    def __init__(self) -> None:
        self.brut = "1002.00"
        self.revision = 1
        self.admission = ADMISSION_OK
        self.acteur_actif = True
        self.appels_brut = 0

    def brut_provider(self, employee_person_id, entrees_declarees):
        self.appels_brut += 1
        return {
            "accepte": True,
            "resultat": {
                "brut_brouillon": self.brut,
                "brut_exact_fraction": {"numerateur_centimes": 1, "denominateur": 60},
                "minutes_regulieres": 4800,
                "devise": "CAD",
                "periode": {k: entrees_declarees["periode"][k] for k in ("debut", "fin", "fuseau")},
                "sources": {
                    "heures_m4": {"ligne_id": "a" * 64, "revision": self.revision, "empreinte_sources": "b" * 64},
                    "contrat_m5": {
                        "contrat_id": "contrat-1",
                        "revision": 1,
                        "ligne_id": "c" * 64,
                        "date_source": "2026-01-01",
                        "source_humaine": "pièce fictive",
                    },
                },
            },
        }

    def admission_provider(self, contexte):
        return self.admission

    def verifier_acteur(self, cnx, acteur):
        if not self.acteur_actif or acteur != OWNER:
            raise service.ServiceErreur(d.refus("ACCES-REFUSE", "propriétaire actif requis"))


@pytest.fixture
def src():
    return Sources()


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'dossiers.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@contextmanager
def tx():
    with stockage.transaction() as cnx:
        yield cnx


def _mid(n: int) -> str:
    return f"{n:032x}"


def _conserver(
    cnx, src, *, e=None, employe=EMPLOYE, mutation=1, attendue=0, type_version="CREATION", motif="", apercu=None
):
    e = e if e is not None else entrees()
    resultat = apercu or service.apercu(
        cnx,
        employee_person_id=employe,
        entrees_brutes=e,
        fournisseur_brut=src.brut_provider,
        fournisseur_admission=src.admission_provider,
    )
    return service.conserver_version(
        cnx,
        acteur=OWNER,
        employee_person_id=employe,
        entrees_brutes=e,
        empreinte_apercu=resultat["empreinte_apercu"],
        version_attendue=attendue,
        type_version=type_version,
        motif=motif,
        mutation_id=_mid(mutation),
        maintenant=NOW,
        fournisseur_brut=src.brut_provider,
        fournisseur_admission=src.admission_provider,
        verifier_acteur=src.verifier_acteur,
    )


def _revue(cnx, src, recu, *, mutation, decision="REVUE_COMPLETEE", note="ok"):
    return service.revue(
        cnx,
        acteur=OWNER,
        dossier_id=recu["dossier_id"],
        numero=recu["numero"],
        hash_version=recu["hash_version"],
        decision=decision,
        note=note,
        mutation_id=_mid(mutation),
        maintenant=NOW,
        fournisseur_brut=src.brut_provider,
        fournisseur_admission=src.admission_provider,
        verifier_acteur=src.verifier_acteur,
    )


def _rouvrir(cnx, src, recu, *, mutation, motif="correction du TD1"):
    return service.rouvrir(
        cnx,
        acteur=OWNER,
        dossier_id=recu["dossier_id"],
        numero=recu["numero"],
        hash_version=recu["hash_version"],
        motif=motif,
        mutation_id=_mid(mutation),
        maintenant=NOW,
        verifier_acteur=src.verifier_acteur,
    )


def _lignes(cnx):
    return cnx.execute(
        select(REGISTRES.c.departement, REGISTRES.c.registre, REGISTRES.c.rang, REGISTRES.c.maillon)
    ).all()


def _compte_par_registre(cnx):
    compte: dict[tuple[str, str], int] = {}
    for ligne in _lignes(cnx):
        cle = (ligne.departement, ligne.registre)
        compte[cle] = compte.get(cle, 0) + 1
    return compte


def test_apercu_ne_persiste_rien_et_dit_les_manques(base, src):
    with tx() as cnx:
        avant = _compte_par_registre(cnx)
        e = entrees(employeur=False)
        resultat = service.apercu(
            cnx,
            employee_person_id=EMPLOYE,
            entrees_brutes=e,
            fournisseur_brut=src.brut_provider,
            fournisseur_admission=src.admission_provider,
        )
        assert _compte_par_registre(cnx) == avant == {}
    calcul = resultat["version"]["calcul"]
    assert calcul["etat"] == "COMPOSE_PREPARATOIRE" and resultat["conservable"] is True
    assert calcul["totaux"]["net_preparatoire"]["etat"] == "CALCULE"
    assert calcul["totaux"]["das_complete"]["etat"] == "INCONNU"
    assert any(m.startswith("fss:") for m in calcul["totaux"]["das_complete"]["manques"])


def test_apercu_est_deterministe(base, src):
    with tx() as cnx:
        kw = dict(
            employee_person_id=EMPLOYE,
            entrees_brutes=entrees(),
            fournisseur_brut=src.brut_provider,
            fournisseur_admission=src.admission_provider,
        )
        assert service.apercu(cnx, **kw)["empreinte_apercu"] == service.apercu(cnx, **kw)["empreinte_apercu"]


def test_creation_chiffre_tout_et_n_ecrit_que_dans_le_registre_du_dossier(base, src):
    with tx() as cnx:
        recu = _conserver(cnx, src)
    assert recu["statut"] == "ECRITE" and recu["numero"] == 1 and recu["etat_calcul"] == "COMPOSE_PREPARATOIRE"
    assert set(recu) == {
        "statut",
        "dossier_id",
        "rang",
        "type",
        "numero",
        "hash_version",
        "type_version",
        "etat_calcul",
    }
    with tx() as cnx:
        assert _compte_par_registre(cnx) == {("m05-financecore", "dossiers_paie_preparatoires"): 1}
        brut = json.dumps([str(ligne.maillon) for ligne in _lignes(cnx)])
        for secret in (EMPLOYE, "1002.00", "770.75", "employeur-fictif", "COMPOSE_PREPARATOIRE", "54.65", "TD1", "td1"):
            assert secret not in brut, secret
        # Le dossier_id est opaque : pas le hash non clé de l'identité.
        assert recu["dossier_id"] not in {
            d.empreinte(["opsys.dossier-paie/v1", EMPLOYE, "employeur-fictif", 2026, 1])[:32],
        }
        lu = journal.lire_dossier(cnx, recu["dossier_id"])
    assert lu["etat"] == "EN_PREPARATION" and len(lu["versions"]) == 1
    figee = lu["versions"][0]["version"]
    assert figee["mentions"]["aucun_versement"] is True and figee["mentions"]["qualification_regles"] == d.QUALIFICATION
    assert figee["cumuls_apres_hypothetiques"]["salaire_rrq_cumul_avant"] == "1002.00"
    assert figee["mentions"]["cumuls_apres"] == "HYPOTHETIQUES_NON_VERSES_NON_CONFIRMES"


def test_rejeu_exact_rend_le_meme_recu_sans_ecriture(base, src):
    with tx() as cnx:
        premier = _conserver(cnx, src)
    with tx() as cnx:
        avant = _lignes(cnx)
        rejoue = _conserver(cnx, src)
        assert rejoue["statut"] == "REJOUEE"
        assert {k: v for k, v in rejoue.items() if k != "statut"} == {k: v for k, v in premier.items() if k != "statut"}
        assert _lignes(cnx) == avant


def test_rejeu_apres_changement_de_source_reste_idempotent(base, src):
    with tx() as cnx:
        premier = _conserver(cnx, src)
    src.revision = 2
    src.brut = "9999.99"
    with tx() as cnx:
        # Même requête exacte (même aperçu d'origine) : le rejeu ne relit ni ne recompose rien.
        e = entrees()
        ancien = service.apercu(
            cnx,
            employee_person_id=EMPLOYE,
            entrees_brutes=e,
            fournisseur_brut=Sources().brut_provider,
            fournisseur_admission=src.admission_provider,
        )
        rejoue = _conserver(cnx, src, apercu=ancien)
        assert rejoue["statut"] == "REJOUEE" and rejoue["hash_version"] == premier["hash_version"]


def test_meme_mutation_autre_charge_refusee_sans_ecriture(base, src):
    with tx() as cnx:
        _conserver(cnx, src)
    with tx() as cnx:
        avant = _lignes(cnx)
        autre = entrees()
        autre["credits_federal"]["TC"] = "17000.00"
        with pytest.raises(service.ServiceErreur) as exc:
            _conserver(cnx, src, e=autre)
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-MUTATION-CONFLIT"
        assert _lignes(cnx) == avant


def test_cas_version_perimee_et_creation_exige_version_zero(base, src):
    with tx() as cnx:
        _conserver(cnx, src)
    with tx() as cnx:
        avant = _lignes(cnx)
        with pytest.raises(service.ServiceErreur) as exc:
            _conserver(cnx, src, mutation=2, attendue=0, type_version="CREATION")
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-VERSION-PERIMEE"
        with pytest.raises(service.ServiceErreur) as exc2:
            _conserver(cnx, src, mutation=3, attendue=0, type_version="CORRECTION")
        assert exc2.value.verdict["code"].startswith("REJ-DOSSIER-PAIE-")
        with pytest.raises(service.ServiceErreur):
            _conserver(cnx, src, mutation=4, attendue=1, type_version="CREATION")
        assert _lignes(cnx) == avant


def test_aperçu_perime_entre_apercu_et_conservation_refuse(base, src):
    with tx() as cnx:
        vu = service.apercu(
            cnx,
            employee_person_id=EMPLOYE,
            entrees_brutes=entrees(),
            fournisseur_brut=src.brut_provider,
            fournisseur_admission=src.admission_provider,
        )
        src.brut = "1100.00"  # les heures M4 ont changé entre l'aperçu et le clic
        with pytest.raises(service.ServiceErreur) as exc:
            _conserver(cnx, src, apercu=vu)
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-SOURCE-MODIFIEE"
        assert _lignes(cnx) == []


def test_source_refusee_ou_periode_invalide_ne_conserve_rien(base, src):
    refus_m4 = lambda *_: {"accepte": False, "verdict": {"code": "REJ-SALAIRE-STRUCTURE-INVALIDE", "detail": "x"}}  # noqa: E731
    with tx() as cnx:
        resultat = service.apercu(
            cnx,
            employee_person_id=EMPLOYE,
            entrees_brutes=entrees(),
            fournisseur_brut=refus_m4,
            fournisseur_admission=src.admission_provider,
        )
        assert resultat["conservable"] is False
        assert resultat["version"]["calcul"]["etat"] == "SOURCE_REFUSEE"
        assert resultat["version"]["calcul"]["totaux"]["net_preparatoire"]["montant"] is None
        with pytest.raises(service.ServiceErreur):
            service.conserver_version(
                cnx,
                acteur=OWNER,
                employee_person_id=EMPLOYE,
                entrees_brutes=entrees(),
                empreinte_apercu=resultat["empreinte_apercu"],
                version_attendue=0,
                type_version="CREATION",
                motif="",
                mutation_id=_mid(1),
                maintenant=NOW,
                fournisseur_brut=refus_m4,
                fournisseur_admission=src.admission_provider,
                verifier_acteur=src.verifier_acteur,
            )
        assert _lignes(cnx) == []
        mauvaise = entrees(2, origine="DECLARE_HISTORIQUE")  # période 2 incohérente avec la date de paie
        autre = service.apercu(
            cnx,
            employee_person_id=EMPLOYE,
            entrees_brutes=mauvaise,
            fournisseur_brut=src.brut_provider,
            fournisseur_admission=src.admission_provider,
        )
        assert autre["conservable"] is False and src.appels_brut == 0


def test_admission_refusee_conserve_un_diagnostic_sans_aucun_poste(base, src):
    src.admission = ADMISSION_REFUSEE
    with tx() as cnx:
        recu = _conserver(cnx, src)
        assert recu["etat_calcul"] == "ADMISSION_REFUSEE"
        lu = journal.lire_dossier(cnx, recu["dossier_id"])
    calcul = lu["versions"][0]["version"]["calcul"]
    assert all(t["montant"] is None for t in calcul["totaux"].values())
    with tx() as cnx:
        with pytest.raises(service.ServiceErreur) as exc:
            _revue(cnx, src, recu, mutation=2)
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-REVUE-INVALIDE"
        # À corriger reste permis : le propriétaire garde la trace de ce qu'il manque.
        assert (
            _revue(cnx, src, recu, mutation=3, decision="A_CORRIGER", note="captures à déposer")["decision"]
            == "A_CORRIGER"
        )


def test_revue_liee_a_version_et_hash_exacts_puis_reouverture_et_correction(base, src):
    with tx() as cnx:
        v1 = _conserver(cnx, src)
    with tx() as cnx:
        faux = {**v1, "hash_version": "0" * 64}
        with pytest.raises(service.ServiceErreur) as exc:
            _revue(cnx, src, faux, mutation=2)
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-VERSION-PERIMEE"
        with pytest.raises(service.ServiceErreur):
            _revue(cnx, src, {**v1, "numero": 2}, mutation=3)
        revue = _revue(cnx, src, v1, mutation=4)
        assert revue["decision"] == "REVUE_COMPLETEE"
    with tx() as cnx:
        # Dossier revu : aucune nouvelle version sans réouverture explicite.
        corrige = entrees()
        corrige["credits_federal"]["TC"] = "17000.00"
        with pytest.raises(service.ServiceErreur) as exc:
            _conserver(cnx, src, e=corrige, mutation=5, attendue=1, type_version="CORRECTION")
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-DOSSIER-REVU"
        with pytest.raises(service.ServiceErreur):
            _revue(cnx, src, v1, mutation=6)  # déjà revu
        reouverture = _rouvrir(cnx, src, v1, mutation=7)
        assert reouverture["depuis_numero"] == 1
        v2 = _conserver(cnx, src, e=corrige, mutation=8, attendue=1, type_version="CORRECTION", motif="TD1 corrigé")
        assert v2["numero"] == 2 and v2["hash_version"] != v1["hash_version"]
        lu = journal.lire_dossier(cnx, v1["dossier_id"])
        assert [v["numero"] for v in lu["versions"]] == [1, 2] and lu["etat"] == "EN_PREPARATION"
        # L'ancienne version reste identique et son hash recalculable.
        assert d.empreinte(lu["versions"][0]["version"]) == v1["hash_version"]
        assert lu["versions"][0]["version"]["entrees"]["credits_federal"]["TC"] == "16452.00"
        # Une revue de la v1 n'est plus acceptée (version non courante).
        with pytest.raises(service.ServiceErreur):
            _revue(cnx, src, v1, mutation=9)
        diff = service.comparer(lu, 1, 2)
    champs = {c["champ"] for c in diff["entrees"]}
    assert champs == {"credits_federal.TC"}
    assert {p["champ"] for p in diff["postes"]} >= {"impot_federal"}
    assert diff["identique"] is False and diff["de"] == 1 and diff["vers"] == 2
    assert diff["etat_calcul"] == {"avant": "COMPOSE_PREPARATOIRE", "apres": "COMPOSE_PREPARATOIRE"}


def test_derive_des_heures_m4_ancienne_version_conservee_rebase_explicite(base, src):
    with tx() as cnx:
        v1 = _conserver(cnx, src)
    src.revision, src.brut = 2, "1100.00"  # correction des heures M4 après le snapshot
    with tx() as cnx:
        controle = service.verifier_version(
            cnx,
            dossier_id=v1["dossier_id"],
            numero=1,
            fournisseur_brut=src.brut_provider,
            fournisseur_admission=src.admission_provider,
        )
        assert controle["reproductible"] is True and controle["sources_inchangees"] is False
        codes = {x["code"] for x in controle["differences"]}
        assert {"SOURCE-HEURES_M4-MODIFIEE", "BRUT-MODIFIE"} <= codes
        with pytest.raises(service.ServiceErreur) as exc:
            _revue(cnx, src, v1, mutation=2)
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-SOURCE-MODIFIEE"
        v2 = _conserver(cnx, src, mutation=3, attendue=1, type_version="REBASE", motif="heures M4 corrigées")
        assert v2["type_version"] == "REBASE"
        lu = journal.lire_dossier(cnx, v1["dossier_id"])
        assert lu["versions"][0]["version"]["sources"]["brut"]["brut_brouillon"] == "1002.00"
        assert lu["versions"][1]["version"]["sources"]["brut"]["brut_brouillon"] == "1100.00"
        assert _revue(cnx, src, v2, mutation=4)["decision"] == "REVUE_COMPLETEE"


def test_moteur_modifie_apres_snapshot_ne_reecrit_pas_l_ancien_dossier(base, src, monkeypatch):
    with tx() as cnx:
        v1 = _conserver(cnx, src)
    vrai = d.calculer_retenue_federale_qc_preparatoire

    def autre_moteur(**kw):
        sortie, verdict = vrai(**kw)
        sortie = json.loads(json.dumps(sortie))
        sortie["retenue_impot_federal"] = "29.00"
        return sortie, verdict

    monkeypatch.setattr(d, "calculer_retenue_federale_qc_preparatoire", autre_moteur)
    with tx() as cnx:
        controle = service.verifier_version(
            cnx,
            dossier_id=v1["dossier_id"],
            numero=1,
            fournisseur_brut=src.brut_provider,
            fournisseur_admission=src.admission_provider,
        )
        assert controle["reproductible"] is False
        assert controle["differences"][0]["code"] == "CALCUL-NON-REPRODUCTIBLE"
        lu = journal.lire_dossier(cnx, v1["dossier_id"])
        postes = {p["id"]: p["montant"] for p in lu["versions"][0]["version"]["calcul"]["matrice"]}
        assert postes["impot_federal"] == "28.00"  # le dossier conservé garde sa valeur
        with pytest.raises(service.ServiceErreur):
            _revue(cnx, src, v1, mutation=2)


def test_acteur_revoque_pendant_traitement_aucune_ecriture(base, src):
    src.acteur_actif = False
    with tx() as cnx:
        with pytest.raises(service.ServiceErreur):
            _conserver(cnx, src)
        assert _lignes(cnx) == []
    src.acteur_actif = True
    with tx() as cnx:
        v1 = _conserver(cnx, src)
    src.acteur_actif = False
    with tx() as cnx:
        avant = _lignes(cnx)
        for appel in (lambda: _revue(cnx, src, v1, mutation=2), lambda: _rouvrir(cnx, src, v1, mutation=3)):
            with pytest.raises(service.ServiceErreur):
                appel()
        assert _lignes(cnx) == avant


def test_panne_tardive_annule_toute_l_ecriture_puis_reprise_sans_doublon(base, src):
    with pytest.raises(RuntimeError, match="panne"), tx() as cnx:
        _conserver(cnx, src)
        raise RuntimeError("panne après l'écriture, avant le commit")
    with tx() as cnx:
        assert _lignes(cnx) == []
        # La reprise avec la même mutation produit une seule version, pas deux.
        premier = _conserver(cnx, src)
    with tx() as cnx:
        assert _conserver(cnx, src)["statut"] == "REJOUEE"
        assert len(journal.lire_dossier(cnx, premier["dossier_id"])["versions"]) == 1


def test_deux_employes_deux_dossiers_et_aucune_fuite_de_revue(base, src):
    with tx() as cnx:
        a = _conserver(cnx, src, employe=EMPLOYE, mutation=1)
        b = _conserver(cnx, src, employe=AUTRE_EMPLOYE, mutation=2)
        assert a["dossier_id"] != b["dossier_id"]
        # La revue du dossier A ne peut pas viser le hash du dossier B.
        croise = {**a, "hash_version": b["hash_version"]}
        with pytest.raises(service.ServiceErreur):
            _revue(cnx, src, croise, mutation=3)
        inconnu = {**a, "dossier_id": "f" * 32}
        with pytest.raises(service.ServiceErreur) as exc:
            _revue(cnx, src, inconnu, mutation=4)
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-INTROUVABLE"
        resumes = service.lister(cnx)
    assert {r["employee_person_id"] for r in resumes} == {EMPLOYE, AUTRE_EMPLOYE}


def _p2(src, cnx, p1, *, mutation, valeurs_falsifiees=None):
    """Période 2 (2026-01-29) avec cumuls simulés depuis la version courante de la période 1."""
    p1_entrees = entrees()
    e = entrees(2, debut="2026-01-15", fin="2026-01-28", date_paie="2026-01-29")
    e["cumuls_avant"]["origine"] = "SIMULE_VERSION_PRECEDENTE"
    e["cumuls_avant"]["source_simulee"] = {
        "dossier_id": p1["dossier_id"],
        "numero_version": p1["numero"],
        "hash_version": p1["hash_version"],
    }
    if valeurs_falsifiees:
        e["cumuls_avant"]["valeurs"].update(valeurs_falsifiees)
    _ = p1_entrees
    return _conserver(cnx, src, e=e, mutation=mutation)


def test_cumul_simule_vient_de_la_version_precedente_jamais_de_l_appelant(base, src):
    with tx() as cnx:
        p1 = _conserver(cnx, src, mutation=1)
        p2 = _p2(src, cnx, p1, mutation=2, valeurs_falsifiees={"ae_salarie_cumul_avant": "0.01"})
        lu = journal.lire_dossier(cnx, p2["dossier_id"])
    entrees_p2 = lu["versions"][0]["version"]["entrees"]
    assert entrees_p2["cumuls_avant"]["valeurs"]["salaire_rrq_cumul_avant"] == "1002.00"
    assert entrees_p2["cumuls_avant"]["valeurs"]["ae_salarie_cumul_avant"] == "13.03"  # la valeur falsifiée est écrasée
    assert entrees_p2["cumuls_avant"]["origine"] == "SIMULE_VERSION_PRECEDENTE"
    assert lu["versions"][0]["version"]["calcul"]["etat"] == "COMPOSE_PREPARATOIRE"


def test_cumul_simule_perime_si_la_periode_precedente_change(base, src):
    with tx() as cnx:
        p1 = _conserver(cnx, src, mutation=1)
        p2 = _p2(src, cnx, p1, mutation=2)
    src.brut, src.revision = "1100.00", 2
    with tx() as cnx:
        p1_v2 = _conserver(cnx, src, mutation=3, attendue=1, type_version="REBASE", motif="heures corrigées")
        controle = service.verifier_version(
            cnx,
            dossier_id=p2["dossier_id"],
            numero=1,
            fournisseur_brut=src.brut_provider,
            fournisseur_admission=src.admission_provider,
        )
        assert "CUMUL-SIMULE-PERIME" in {x["code"] for x in controle["differences"]}
        # Réutiliser la version 1 de la période 1 comme source est refusé : CUMUL-PERIME.
        with pytest.raises(service.ServiceErreur) as exc:
            _p2(src, cnx, p1, mutation=4)
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-CUMUL-PERIME"
        assert p1_v2["numero"] == 2


def test_cumul_simule_source_autre_employe_ou_periode_refuse(base, src):
    with tx() as cnx:
        p1 = _conserver(cnx, src, employe=AUTRE_EMPLOYE, mutation=1)
        avant = _lignes(cnx)
        with pytest.raises(service.ServiceErreur) as exc:
            _p2_pour(src, cnx, p1, EMPLOYE, mutation=2)
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-CUMUL-INVALIDE"
        assert _lignes(cnx) == avant


def _p2_pour(src, cnx, p1, employe, *, mutation):
    e = entrees(2, debut="2026-01-15", fin="2026-01-28", date_paie="2026-01-29")
    e["cumuls_avant"]["origine"] = "SIMULE_VERSION_PRECEDENTE"
    e["cumuls_avant"]["source_simulee"] = {
        "dossier_id": p1["dossier_id"],
        "numero_version": p1["numero"],
        "hash_version": p1["hash_version"],
    }
    return _conserver(cnx, src, e=e, employe=employe, mutation=mutation)


def test_export_exige_une_revue_complete_courante_et_des_sources_inchangees(base, src):
    with tx() as cnx:
        v1 = _conserver(cnx, src)

    def exporter(cnx, mutation, fmt="json", recu=None):
        recu = recu or v1
        return service.exporter(
            cnx,
            acteur=OWNER,
            dossier_id=recu["dossier_id"],
            numero=recu["numero"],
            hash_version=recu["hash_version"],
            format_export=fmt,
            mutation_id=_mid(mutation),
            maintenant=NOW,
            liens_officiels=LIENS,
            fournisseur_brut=src.brut_provider,
            fournisseur_admission=src.admission_provider,
            verifier_acteur=src.verifier_acteur,
        )

    with tx() as cnx:
        with pytest.raises(service.ServiceErreur) as exc:
            exporter(cnx, 2)
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-EXPORT-REFUSE"  # pas de revue
        _revue(cnx, src, v1, mutation=3)
        with pytest.raises(service.ServiceErreur):
            exporter(cnx, 4, fmt="pdf")
        src.revision = 2
        with pytest.raises(service.ServiceErreur) as exc2:
            exporter(cnx, 5)
        assert exc2.value.verdict["code"] == "REJ-DOSSIER-PAIE-SOURCE-MODIFIEE"
        src.revision = 1
        avant = _lignes(cnx)
        with pytest.raises(service.ServiceErreur):
            service.lire_export(
                cnx,
                dossier_id=v1["dossier_id"],
                numero=1,
                hash_version=v1["hash_version"],
                format_export="json",
                liens_officiels=LIENS,
            )  # lecture sans export audité
        assert _lignes(cnx) == avant


def test_export_reproductible_audite_minimal_et_echappe(base, src):
    with tx() as cnx:
        v1 = _conserver(cnx, src)
        _revue(cnx, src, v1, mutation=2, note='<script>alert("x")</script> & "citation"')
        contenus = {}
        for numero, fmt in ((3, "json"), (4, "html")):
            recu = service.exporter(
                cnx,
                acteur=OWNER,
                dossier_id=v1["dossier_id"],
                numero=1,
                hash_version=v1["hash_version"],
                format_export=fmt,
                mutation_id=_mid(numero),
                maintenant=NOW,
                liens_officiels=LIENS,
                fournisseur_brut=src.brut_provider,
                fournisseur_admission=src.admission_provider,
                verifier_acteur=src.verifier_acteur,
            )
            octets, empreinte = service.lire_export(
                cnx,
                dossier_id=v1["dossier_id"],
                numero=1,
                hash_version=v1["hash_version"],
                format_export=fmt,
                liens_officiels=LIENS,
            )
            assert recu["empreinte_export"] == empreinte
            contenus[fmt] = octets
            # Reconstruction identique octet par octet, après relecture complète du journal.
            assert (
                service.lire_export(
                    cnx,
                    dossier_id=v1["dossier_id"],
                    numero=1,
                    hash_version=v1["hash_version"],
                    format_export=fmt,
                    liens_officiels=LIENS,
                )[0]
                == octets
            )
    doc = json.loads(contenus["json"])
    assert doc["schema"] == export.SCHEMA_EXPORT and doc["mode"] == "PREPARATOIRE"
    assert doc["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE" and doc["documents_officiels_emis"] == []
    assert doc["totaux"]["net_preparatoire"]["montant"] == "770.75"
    assert doc["employe"] == {"reference_opsys": EMPLOYE}
    assert doc["dossier"]["revue_interne"]["portee"] == "REVUE_INTERNE_PROPRIETAIRE_NON_FISCALE"
    assert doc["pour_verification_webras"]["liens_officiels"][0]["id"] == "webras"
    assert any(s["id"] == "rq_tp1015f_fss" for s in doc["sources_reglementaires"])
    texte = contenus["json"].decode()
    for interdit in ("taux_horaire", "nas", "iban", "mot_de_passe", "csrf", "secret"):
        assert interdit not in texte.lower()
    page = contenus["html"].decode()
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "NON_QUALIFIEE_POUR_PAIE" in page and "Aucun salaire versé" in page
    assert "http-equiv" not in page and "<form" not in page and "src=" not in page
    with tx() as cnx:
        lu = journal.lire_dossier(cnx, v1["dossier_id"])
    assert [e["format"] for e in lu["exports"]] == ["json", "html"]
    # L'export lui-même n'est jamais conservé en clair dans le journal : seulement son empreinte.
    with tx() as cnx:
        assert "770.75" not in json.dumps([str(ligne.maillon) for ligne in _lignes(cnx)])


def test_export_d_un_dossier_non_courant_ou_rouvert_est_refuse(base, src):
    with tx() as cnx:
        v1 = _conserver(cnx, src)
        _revue(cnx, src, v1, mutation=2)
        service.exporter(
            cnx,
            acteur=OWNER,
            dossier_id=v1["dossier_id"],
            numero=1,
            hash_version=v1["hash_version"],
            format_export="json",
            mutation_id=_mid(3),
            maintenant=NOW,
            liens_officiels=LIENS,
            fournisseur_brut=src.brut_provider,
            fournisseur_admission=src.admission_provider,
            verifier_acteur=src.verifier_acteur,
        )
        _rouvrir(cnx, src, v1, mutation=4)
        with pytest.raises(service.ServiceErreur) as exc:
            service.lire_export(
                cnx,
                dossier_id=v1["dossier_id"],
                numero=1,
                hash_version=v1["hash_version"],
                format_export="json",
                liens_officiels=LIENS,
            )
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-EXPORT-REFUSE"


# ---------------------------------------------------------------- intégrité du journal


def _modifier_maillon(cnx, rang, transformation):
    from opsys.stockage import codec

    ligne = cnx.execute(select(REGISTRES.c.maillon).where(REGISTRES.c.rang == rang)).scalar_one()
    nouveau = transformation(codec.decoder(ligne))
    cnx.execute(
        text("UPDATE registres_maillons SET maillon = :m WHERE rang = :r"), {"m": codec.encoder(nouveau), "r": rang}
    )


@pytest.mark.parametrize(
    "alteration",
    [
        lambda m: {**m, "ciphertext": m["ciphertext"][:-2] + ("00" if m["ciphertext"][-2:] != "00" else "01")},
        lambda m: {**m, "mutation_mac": "0" * 64},
        lambda m: {**m, "precedent_sha256": "1" * 64},
        lambda m: {**m, "dossier_id": "e" * 32},
        lambda m: {**m, "nonce": "00" * 12},
        lambda m: {**m, "type": "REVUE"},
        lambda m: {k: v for k, v in m.items() if k != "acteur_mac"},
    ],
)
def test_donnees_alterees_ferment_la_lecture_sans_resultat_partiel(base, src, alteration):
    with tx() as cnx:
        v1 = _conserver(cnx, src)
    with tx() as cnx:
        _modifier_maillon(cnx, 0, alteration)
    with tx() as cnx:
        for appel in (
            lambda: journal.lire_dossier(cnx, v1["dossier_id"]),
            lambda: service.lister(cnx),
            lambda: _revue(cnx, src, v1, mutation=2),
        ):
            with pytest.raises(journal.JournalCorrompu) as exc:
                appel()
            assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-DONNEES-CORROMPUES"


def test_cle_detruite_rend_le_dossier_illisible_sans_perte_silencieuse(base, src):
    from opsys import cles_chiffrement

    with tx() as cnx:
        v1 = _conserver(cnx, src)
    with tx() as cnx:
        assert cles_chiffrement.detruire(cnx, journal.PORTEE_CLE, v1["dossier_id"]) is True
    with tx() as cnx, pytest.raises(journal.JournalCorrompu):
        journal.lire_dossier(cnx, v1["dossier_id"])


def test_lecture_hors_transaction_courante_refusee(base):
    with tx() as cnx:
        pass
    with pytest.raises(journal.JournalErreur):
        journal.lire_tout(cnx)


def test_nonce_deterministe_distinct_par_clair_et_chiffre_different_par_evenement(base, src):
    with tx() as cnx:
        v1 = _conserver(cnx, src)
        _revue(cnx, src, v1, mutation=2, note="a")
        enveloppes = [m for m in (ligne.maillon for ligne in _lignes(cnx))]
    from opsys.stockage import codec

    decodees = [codec.decoder(m) if isinstance(m, str) else m for m in enveloppes]
    assert len({e["nonce"] for e in decodees}) == len(decodees)
    assert copie(decodees[0])["type"] == "VERSION" and decodees[1]["type"] == "REVUE"


def test_doublon_de_periode_sous_une_autre_reference_d_employeur_refuse(base, src):
    with tx() as cnx:
        _conserver(cnx, src, mutation=1)
        autre = entrees()
        autre["employeur_reference"] = "employeur-fictif-bis"
        avant = _lignes(cnx)
        with pytest.raises(service.ServiceErreur) as exc:
            _conserver(cnx, src, e=autre, mutation=2)
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-DOSSIER-DOUBLON"
        assert _lignes(cnx) == avant


def test_ecritures_concurrentes_une_seule_gagne_sans_ecriture_partielle(base, src):
    """Deux transactions réelles visent la même version attendue : une version, un refus VERSION-PERIMEE."""
    import threading

    with tx() as cnx:
        v1 = _conserver(cnx, src, mutation=1)
    corrige_a, corrige_b = entrees(), entrees()
    corrige_a["credits_federal"]["TC"] = "17000.00"
    corrige_b["credits_federal"]["TC"] = "18000.00"
    barriere = threading.Barrier(2)
    resultats: dict[str, object] = {}

    def travailler(nom, e, mutation):
        try:
            with tx() as cnx:
                apercu_local = service.apercu(
                    cnx,
                    employee_person_id=EMPLOYE,
                    entrees_brutes=e,
                    fournisseur_brut=src.brut_provider,
                    fournisseur_admission=src.admission_provider,
                )
            barriere.wait(timeout=10)
            with tx() as cnx:
                resultats[nom] = _conserver(
                    cnx,
                    src,
                    e=e,
                    mutation=mutation,
                    attendue=1,
                    type_version="CORRECTION",
                    apercu=apercu_local,
                )
        except Exception as exc:  # noqa: BLE001 — le refus attendu est transporté vers le fil principal
            resultats[nom] = exc

    fils = [threading.Thread(target=travailler, args=args) for args in (("a", corrige_a, 10), ("b", corrige_b, 11))]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=60)
    gagnants = [r for r in resultats.values() if isinstance(r, dict)]
    perdants = [r for r in resultats.values() if isinstance(r, service.ServiceErreur)]
    assert len(gagnants) == 1 and len(perdants) == 1, resultats
    assert perdants[0].verdict["code"] == "REJ-DOSSIER-PAIE-VERSION-PERIMEE"
    with tx() as cnx:
        lu = journal.lire_dossier(cnx, v1["dossier_id"])
        assert [v["numero"] for v in lu["versions"]] == [1, 2]
        assert _compte_par_registre(cnx) == {("m05-financecore", "dossiers_paie_preparatoires"): 2}


def test_revue_complete_et_export_refuses_tant_qu_un_total_est_inconnu(base, src):
    inconnue = entrees()
    inconnue["classification"]["regime_ccq"] = "INCONNU"
    with tx() as cnx:
        recu = _conserver(cnx, src, e=inconnue)
        lu = journal.lire_dossier(cnx, recu["dossier_id"])
        # Composition sans prérequis : aucun cumul « après » n'est proposé à la période suivante.
        assert lu["versions"][0]["version"]["cumuls_apres_hypothetiques"] is None
        avant = _lignes(cnx)
        with pytest.raises(service.ServiceErreur) as exc:
            _revue(cnx, src, recu, mutation=2)
        assert exc.value.verdict["code"] == "REJ-DOSSIER-PAIE-REVUE-INVALIDE"
        assert "net_preparatoire" in exc.value.verdict["detail"]
        assert _lignes(cnx) == avant
        assert _revue(cnx, src, recu, mutation=3, decision="A_CORRIGER", note="classification à établir")
    incomplet = entrees(employeur=False)  # DAS et coût employeur inconnus
    with tx() as cnx:
        recu2 = _conserver(cnx, src, e=incomplet, employe=AUTRE_EMPLOYE, mutation=4)
        with pytest.raises(service.ServiceErreur) as exc2:
            _revue(cnx, src, recu2, mutation=5)
        assert "das_complete" in exc2.value.verdict["detail"]


def test_cumul_simule_refuse_si_nature_calendrier_ou_ecart_different(base, src):
    with tx() as cnx:
        p1 = _conserver(cnx, src, mutation=1)  # dossier fictif, première paie 2026-01-15
        for modif, mutation in (
            (lambda e: e.update(fictif=False), 2),
            (lambda e: e["periode"].update(premiere_date_paie_annee="2026-01-08"), 3),
        ):
            e = entrees(2, debut="2026-01-15", fin="2026-01-28", date_paie="2026-01-29")
            e["cumuls_avant"]["origine"] = "SIMULE_VERSION_PRECEDENTE"
            e["cumuls_avant"]["source_simulee"] = {
                "dossier_id": p1["dossier_id"],
                "numero_version": 1,
                "hash_version": p1["hash_version"],
            }
            modif(e)
            with pytest.raises(service.ServiceErreur) as exc:
                _conserver(cnx, src, e=e, mutation=mutation)
            assert exc.value.verdict["code"].startswith("REJ-DOSSIER-PAIE-")


def test_poste_calcule_sans_montant_devient_inconnu_et_aucun_total_calcule():
    from m5_financecore import dossier_paie_preparatoire as dossier

    sans_montant = dossier._poste("x", "x", "employe", "x", "CALCULE", None, moteur="x")
    assert dossier._somme([sans_montant]) is None
    connu = dossier._poste("y", "y", "employe", "y", "NON_APPLICABLE", None, moteur="y")
    assert dossier._somme([connu]) is not None


def test_controle_d_etat_est_rejoue_et_refuse_sans_ecriture(base, src):
    with tx() as cnx:
        v1 = _conserver(cnx, src)
        avant = _lignes(cnx)

        def toujours_refuse(_tous, _courant):
            raise service.ServiceErreur(d.refus("ETAT-INVALIDE", "précondition devenue fausse"))

        with pytest.raises(service.ServiceErreur):
            journal.ajouter(
                cnx,
                dossier_id=v1["dossier_id"],
                type_evt="REVUE",
                mutation_id=_mid(9),
                acteur=OWNER,
                horodatage=NOW,
                version_attendue=1,
                requete_sha256="0" * 64,
                verifier_acteur=src.verifier_acteur,
                contenu={"numero": 1, "hash_version": v1["hash_version"], "decision": "A_CORRIGER", "note": ""},
                controle=toujours_refuse,
            )
        assert _lignes(cnx) == avant
