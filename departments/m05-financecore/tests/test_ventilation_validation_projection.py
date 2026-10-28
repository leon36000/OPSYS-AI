"""Contrat M4 V2 : fixture fictive du commit 07cacb3ab, sans producteur réel."""

import copy
import json

import pytest
from m5_financecore import encodage

FIXTURE = r"""
{
  "fictif": true,
  "description": "Fixture de structure uniquement : références fictives, non issues de registres réels.",
  "projection": {
    "version": "opsys.m4.temps_certifies.v2",
    "instance_id": "00000000-0000-4000-8000-000000000001",
    "chantier_id": null,
    "intervention_id": "573a0a925ae3caa1aa0669bc038867b5c96190ca06ed26384ac0df625c4689f3",
    "lead_id": "lead-fictif-001",
    "wct": {
      "wct_id": "481805f0d46ef8f6dac56f0adedc9b31b63182392cda015f67b1df5ca78c37f0",
      "source_ligne_id": "3a1c4ddd88a80c94ce1e4d5ad633e0d751a053619d46b9803ffdad6ae2b8df29",
      "hash_maillon": "d9586ad19c672eea1fff657d52778c449fcbe6880f1c6bce31ac2b490d4b0638",
      "horodatage_transition": "2030-06-07T13:05:00-04:00",
      "horodatage_completion": "2030-06-07T17:00:00+00:00",
      "statut": "completed_pending_review",
      "duree_reelle_minutes": 390
    },
    "sources": {
      "principal": {
        "tete": "3a1c4ddd88a80c94ce1e4d5ad633e0d751a053619d46b9803ffdad6ae2b8df29",
        "empreinte_snapshot": "212b51d01b26fa03d14e48f2cd4097d31ce5502ae8aa1e5978cc623ad5211bda"
      },
      "visites": {
        "tete": "7dd3e337232d0c78c028ec992e0fca74493534964ef0440478fc93b268d53e3c",
        "empreinte_snapshot": "f41fbf02634a7fb6a1d7d6f5d18a65a996ad851795492d6834a161ae751e74bd"
      },
      "compositions": {
        "tete": "e37e140195984aeb1712caff6ac74638f4c290ab0e2d569db75a0507814e6e05",
        "empreinte_snapshot": "84b2f7a6daddfbefa6d6aca6f70a8631e39d1a55e634d5df3fc5d21646bba683"
      }
    },
    "visites": [
      {
        "visite_id": "476e2f7bf3bbbc884e8eb49891a5ec4260cb6bcdc0890493c67e898767975264",
        "ancre": {
          "intervention_id": "573a0a925ae3caa1aa0669bc038867b5c96190ca06ed26384ac0df625c4689f3",
          "plan_id": "77f93e493c104702eaf1eb5c5a613fe50d4636c6ade83b38e739b6e35e8ecb8c",
          "source_application_id": "7eb254b3f4301c951c6deb201f19c6d055c19e8374b440add9eaa47f2109edd3",
          "source_ligne_id": "b8301f002b5e781043547d0f205bfb1529ae9825af2fb63386840c4d3e674043"
        },
        "equipe_planifiee_id": "equipe-A-fictive",
        "equipe_pointee": {
          "statut": "identifiee",
          "identifiant": "equipe-A-fictive",
          "justification": "egalite_route_et_prevision"
        },
        "identifiant_pointe": "equipe-A-fictive",
        "ouverture": {
          "source_ligne_id": "275a4c86d44062ec363ce17f049b5e6c9445ffd733fa029054608e96f4a9b36a",
          "horodatage": "2030-06-03T08:00:00-04:00"
        },
        "evenements": [
          {
            "type": "en_route",
            "source_ligne_id": "b26c7b3f525b6194a268a9be7f06a089976b6c6e304a6a5c76e1a539322319fc",
            "horodatage": "2030-06-03T08:30:00-04:00",
            "revue_gps": null
          },
          {
            "type": "arrivee",
            "source_ligne_id": "ef82cf9597d685cf0f802d627620b85f628a60be09910e018cb70b2787bc39a5",
            "horodatage": "2030-06-03T09:00:00-04:00",
            "revue_gps": {
              "statut": "coherent",
              "demande_ligne_id": null,
              "resolution_ligne_id": null
            }
          },
          {
            "type": "pause_debut",
            "source_ligne_id": "a6465ad577b2a359cc9aab0ff82121fd6770c3a915ce21ee11b43af05a0864c8",
            "horodatage": "2030-06-03T10:00:00-04:00",
            "revue_gps": null
          },
          {
            "type": "pause_fin",
            "source_ligne_id": "789c44cd2159b048a49d01d8b2127a1d43aa02d5c5d1b2cf7f3e8ffa0c7dc58f",
            "horodatage": "2030-06-03T10:30:00-04:00",
            "revue_gps": null
          },
          {
            "type": "depart",
            "source_ligne_id": "218d99234b6655863ed7d3d909a8661af853a817768fba86d458c8dadf76b7cc",
            "horodatage": "2030-06-03T12:00:00-04:00",
            "revue_gps": {
              "statut": "coherent",
              "demande_ligne_id": null,
              "resolution_ligne_id": null
            }
          }
        ],
        "fermeture": {
          "source_ligne_id": "c1bd9eb79ef3292f1a839516f42fc706fd734c614913ccade65d10f4d3f00e8b",
          "horodatage": "2030-06-03T12:01:00-04:00"
        },
        "composition_declaree": {
          "statut": "declaree",
          "jour": "2030-06-03",
          "equipe_id": "equipe-A-fictive",
          "source_ligne_id": "dceb3072bd89ff8f1557e6b4d2d66aae79b80a16d47c63dafa978682a3bf90c5",
          "revision": 1,
          "horodatage": "2030-06-03T07:45:00-04:00",
          "membres": [
            "lundi-personne.fictive"
          ]
        },
        "presence_individuelle": {
          "statut": "inconnue"
        },
        "minutes": {
          "travail": 150,
          "pause": 30,
          "deplacement": 30
        }
      },
      {
        "visite_id": "7dd3e337232d0c78c028ec992e0fca74493534964ef0440478fc93b268d53e3c",
        "ancre": {
          "intervention_id": "573a0a925ae3caa1aa0669bc038867b5c96190ca06ed26384ac0df625c4689f3",
          "plan_id": "7eb6abe3ecb3934b104674f725ab0a2432c402f6e5bc8cd5bb38d460d9a0351d",
          "source_application_id": "1f27f4db0a4ec755879a78d907430b2fd13cb9f6770d6d150c2a51a692e80fba",
          "source_ligne_id": "18a3aea9e2fb935f12a62a74fcc4f48a7c879621f07050ff414d6580050ff1f4"
        },
        "equipe_planifiee_id": "equipe-B-fictive",
        "equipe_pointee": {
          "statut": "identifiee",
          "identifiant": "equipe-B-fictive",
          "justification": "egalite_route_et_prevision"
        },
        "identifiant_pointe": "equipe-B-fictive",
        "ouverture": {
          "source_ligne_id": "799cb0514b8f0ba2d70dc58042a84fe7257ceee1347f7c6eaa9249803d29aa60",
          "horodatage": "2030-06-07T08:00:00-04:00"
        },
        "evenements": [
          {
            "type": "en_route",
            "source_ligne_id": "39a7f96640920023ae45c22b721fc0f75ba165abe628540f050b724e56fbdb01",
            "horodatage": "2030-06-07T12:30:00+00:00",
            "revue_gps": null
          },
          {
            "type": "arrivee",
            "source_ligne_id": "ce790cd910dbfb3082369ca28408b2a0a140aa0f73cb8d5cee933e561a8db637",
            "horodatage": "2030-06-07T13:00:00+00:00",
            "revue_gps": {
              "statut": "coherent",
              "demande_ligne_id": null,
              "resolution_ligne_id": null
            }
          },
          {
            "type": "depart",
            "source_ligne_id": "d21edee78ff85628c52230c91e5c1223c0275aff025a4202061ea73cc54ccc8e",
            "horodatage": "2030-06-07T17:00:00+00:00",
            "revue_gps": {
              "statut": "coherent",
              "demande_ligne_id": null,
              "resolution_ligne_id": null
            }
          }
        ],
        "fermeture": {
          "source_ligne_id": "c82636cfd096fc9de1e91b6835f15968909191d534b5dd9cd817f9bf8f5fdcae",
          "horodatage": "2030-06-07T13:01:00-04:00"
        },
        "composition_declaree": {
          "statut": "declaree",
          "jour": "2030-06-07",
          "equipe_id": "equipe-B-fictive",
          "source_ligne_id": "e37e140195984aeb1712caff6ac74638f4c290ab0e2d569db75a0507814e6e05",
          "revision": 1,
          "horodatage": "2030-06-07T07:45:00-04:00",
          "membres": [
            "vendredi-personne.fictive"
          ]
        },
        "presence_individuelle": {
          "statut": "inconnue"
        },
        "minutes": {
          "travail": 240,
          "pause": 0,
          "deplacement": 30
        }
      }
    ],
    "totaux": {
      "travail": 390,
      "pause": 30,
      "deplacement": 60
    },
    "revue_chantier": {
      "statut": "en_attente",
      "source_ligne_id": "3a1c4ddd88a80c94ce1e4d5ad633e0d751a053619d46b9803ffdad6ae2b8df29"
    },
    "inconnus": [
      {
        "code": "chantier_id_indisponible",
        "visite_id": null
      },
      {
        "code": "presence_individuelle_non_observee",
        "visite_id": "476e2f7bf3bbbc884e8eb49891a5ec4260cb6bcdc0890493c67e898767975264"
      },
      {
        "code": "presence_individuelle_non_observee",
        "visite_id": "7dd3e337232d0c78c028ec992e0fca74493534964ef0440478fc93b268d53e3c"
      }
    ],
    "empreinte": "d8b06fff770867c753ef6d7c9313d8f49bf362759caad281057b9ea21c57b21d"
  }
}

"""


def _cas():
    projection = json.loads(FIXTURE)["projection"]
    sources = copy.deepcopy(projection["sources"])
    cas = encodage.empreinte(
        "m4.temps_certifies.cas.v2",
        projection["instance_id"],
        projection["wct"]["wct_id"],
        *(sources[k]["empreinte_snapshot"] for k in ("principal", "visites", "compositions")),
    )
    return projection, sources, cas


def _validation(projection, sources, cas):
    from m5_financecore.validation_projection_visites import valider_projection

    return valider_projection(
        projection,
        instance_id=projection["instance_id"],
        wct_id=projection["wct"]["wct_id"],
        source_attendue=cas,
        sources_actuelles=sources,
    )


def _signer(p):
    p["empreinte"] = encodage.empreinte("m4.temps_certifies.v2", {k: v for k, v in p.items() if k != "empreinte"})


def test_fixture_valide_mais_revue_en_attente_ne_certifie_pas_un_cout():
    p, sources, cas = _cas()
    r = _validation(p, sources, cas)
    assert r["valide"] is True
    assert r["exploitable"] is False
    assert r["raisons"]


def test_revue_verifiee_avec_sources_stables():
    p, sources, cas = _cas()
    p["revue_chantier"]["statut"] = "verifiee"
    _signer(p)
    r = _validation(p, sources, cas)
    assert r["valide"] is True and r["exploitable"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(version="v1"),
        lambda p: p.update(surprise=True),
        lambda p: p["wct"].update(duree_reelle_minutes=True),
        lambda p: p["wct"].update(duree_reelle_minutes=391),
        lambda p: p["totaux"].update(travail=391),
        lambda p: p["visites"].reverse(),
        lambda p: p["visites"].append(copy.deepcopy(p["visites"][0])),
        lambda p: p["visites"][0]["ancre"].update(intervention_id="autre"),
        lambda p: p["visites"][0]["evenements"][0].update(horodatage="2030-06-03T08:30:00"),
        lambda p: p["visites"][0]["evenements"][1]["revue_gps"].update(statut="rejetee"),
        lambda p: p["visites"][0]["minutes"].update(travail=-1),
        lambda p: p["visites"][0]["minutes"].update(travail=150.0),
        lambda p: p["inconnus"].clear(),
        lambda p: p["visites"][0]["presence_individuelle"].update(statut="connue"),
        lambda p: p["visites"][0]["equipe_pointee"].update(identifiant="autre"),
        lambda p: p["visites"][0]["composition_declaree"].update(membres=["fictif"] * 51),
        lambda p: p["sources"]["principal"].update(tete="invalid"),
    ],
)
def test_contrat_incoherent_refuse_meme_avec_empreinte_recalculee(mutation):
    p, sources, cas = _cas()
    mutation(p)
    _signer(p)
    assert _validation(p, sources, cas)["valide"] is False


def test_empreinte_et_sources_perimees_refusees():
    p, sources, cas = _cas()
    p["empreinte"] = "0" * 64
    assert not _validation(p, sources, cas)["valide"]
    p, sources, cas = _cas()
    sources["visites"]["empreinte_snapshot"] = "0" * 64
    assert not _validation(p, sources, cas)["valide"]
    p, sources, cas = _cas()
    assert not _validation(p, sources, "0" * 64)["valide"]


def test_identites_different_refusees():
    from m5_financecore.validation_projection_visites import valider_projection

    p, sources, cas = _cas()
    assert not valider_projection(
        p, instance_id="autre", wct_id=p["wct"]["wct_id"], source_attendue=cas, sources_actuelles=sources
    )["valide"]
    assert not valider_projection(
        p, instance_id=p["instance_id"], wct_id="autre", source_attendue=cas, sources_actuelles=sources
    )["valide"]


def test_depart_arbitre_apres_premier_depart_est_conserve():
    p, sources, cas = _cas()
    precedent = p["visites"][0]["evenements"][-1]
    depart = copy.deepcopy(precedent)
    depart["source_ligne_id"] = "a" * 64
    depart["horodatage"] = "2030-06-03T12:00:30-04:00"
    depart["revue_gps"] = {"statut": "validee", "demande_ligne_id": "b" * 64, "resolution_ligne_id": "c" * 64}
    p["visites"][0]["evenements"].append(depart)
    _signer(p)
    assert _validation(p, sources, cas)["valide"]


@pytest.mark.parametrize(
    "changement",
    [
        lambda p: p["visites"][0]["evenements"][0].update(type=[]),
        lambda p: p["wct"].update(statut=[]),
        lambda p: p["revue_chantier"].update(statut=[]),
        lambda p: p["visites"][0]["composition_declaree"].update(statut=[]),
        lambda p: p["visites"][0]["evenements"][1]["revue_gps"].update(statut=[]),
    ],
)
def test_mauvais_types_refuses_sans_exception(changement):
    p, sources, cas = _cas()
    changement(p)
    _signer(p)
    assert not _validation(p, sources, cas)["valide"]


def test_chevauchement_entre_visites_est_refuse():
    p, sources, cas = _cas()
    p["visites"][1]["evenements"][0]["horodatage"] = "2030-06-03T11:00:00-04:00"
    p["visites"][1]["ouverture"]["horodatage"] = "2030-06-03T10:00:00-04:00"
    _signer(p)
    assert not _validation(p, sources, cas)["valide"]


def test_completion_doît_correspondre_au_dernier_depart():
    p, sources, cas = _cas()
    p["wct"]["horodatage_completion"] = "2030-06-07T18:00:00+00:00"
    _signer(p)
    assert not _validation(p, sources, cas)["valide"]


def test_equipe_non_identifiee_ne_permet_pas_de_certifier_un_cout():
    p, sources, cas = _cas()
    p["revue_chantier"]["statut"] = "verifiee"
    p["visites"][0]["equipe_pointee"] = {"statut": "inconnue", "identifiant": None, "justification": "indeterminee"}
    p["inconnus"].insert(2, {"code": "equipe_pointee_indeterminee", "visite_id": p["visites"][0]["visite_id"]})
    _signer(p)
    r = _validation(p, sources, cas)
    assert r["valide"] is True and r["exploitable"] is False


def test_projection_oversize_refusee():
    p, sources, cas = _cas()
    p["lead_id"] = "f" * 65536
    _signer(p)
    assert not _validation(p, sources, cas)["valide"]


def test_cent_pauses_et_depart_arbitre_restent_dans_la_borne_du_contrat():
    from datetime import datetime, timedelta

    p, sources, cas = _cas()
    evenements = p['visites'][0]['evenements']
    debut = datetime.fromisoformat('2030-06-03T10:00:00-04:00')
    pauses = []
    for i in range(100):
        for j, typ in enumerate(('pause_debut', 'pause_fin')):
            pauses.append({'type': typ, 'source_ligne_id': f'{i * 2 + j + 1:064x}',
                           'horodatage': (debut + timedelta(seconds=i * 18 + j * 18)).isoformat(),
                           'revue_gps': None})
    depart = copy.deepcopy(evenements[-1])
    depart.update(source_ligne_id='a' * 64, horodatage='2030-06-03T12:00:30-04:00',
                  revue_gps={'statut': 'validee', 'demande_ligne_id': 'b' * 64, 'resolution_ligne_id': 'c' * 64})
    p['visites'][0]['evenements'] = evenements[:2] + pauses + [evenements[-1], depart]
    _signer(p)
    assert _validation(p, sources, cas)['valide']


def test_minutes_impossibles_ne_sont_pas_certifiees_meme_si_la_somme_correspond():
    p, sources, cas = _cas()
    p['visites'][0]['minutes']['travail'] = 10000
    p['totaux']['travail'] = 10240
    p['wct']['duree_reelle_minutes'] = 10240
    p['revue_chantier']['statut'] = 'verifiee'
    _signer(p)
    assert not _validation(p, sources, cas)['valide']
