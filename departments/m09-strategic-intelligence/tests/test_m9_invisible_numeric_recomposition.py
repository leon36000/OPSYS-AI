import pytest
import test_recommandation_gouvernee as reco_tests
from m9_strategic_intelligence import conseil
from m9_strategic_intelligence import recommandation_gouvernee as rg

MARQUES = [
    "\u200b", "\u2060", "\u2063", "\u200d", "\ufeff", "\u00ad", "\u0307", "\u0338", "\u034f",
    "\ufe0f", "\u0903", "\u20dd", "\u20e3", "\u202e", "\u2007", "\u2008", "\u2009", "\u205f",
]
SIGNES = ["-", "\u2212", "\uff0d", "\ufe63"]
MARQUES_SIGNE = [
    "\u200b", "\u2060", "\u2063", "\u200d", "\ufeff", "\u00ad", "\u0307", "\u0338", "\u034f",
    "\ufe0f", "\u0903", "\u20dd", "\u20e3", "\u202e",
]


def _formes_signe_devise(signe, marque, nombre="8400.00"):
    return [
        f"{signe}{marque}{nombre} $",
        f"{signe}${marque}{nombre}",
        f"${signe}{marque}{nombre}",
        f"{signe}{marque}${nombre}",
        f"${marque}{signe}{nombre}",
    ]


@pytest.mark.parametrize("marque", MARQUES)
def test_admission_conseil_refuse_montant_recompose_par_marque_non_citee(marque):
    valeur_source = "400.00 $"
    texte = f"Gain 8{marque}400.00 $"
    sortie = {
        "affirmations": [
            {"id": "O1", "nature": "observation_source", "reference": "r1", "valeur": valeur_source},
            {"id": "H1", "nature": "hypothese", "enonce": texte},
        ]
    }
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        conseil.admettre_proposition(sortie, sources={"r1": valeur_source})


@pytest.mark.parametrize("marque", MARQUES)
def test_recommandation_refuse_fragments_cites_separement_recomposes(marque, monkeypatch):
    reco = reco_tests.reco_valide()
    adresse_huit = reco["chiffres"][0]["source"]["adresse"]
    adresse_quatre_cents = reco["chiffres"][1]["source"]["adresse"]
    reco["chiffres"][0]["valeur"] = "8"
    reco["chiffres"][1]["valeur"] = "400.00"
    monkeypatch.setitem(reco_tests.FAITS, adresse_huit, "8")
    monkeypatch.setitem(reco_tests.FAITS, adresse_quatre_cents, "400.00")
    reco["options"][0]["description"] = f"Gain 8{marque}400.00 $"

    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        reco_tests.controler(reco)


@pytest.mark.parametrize("marque", ["\u200b", "\u2060", "\u00ad", "\u0307", "\u0338"])
def test_citation_numerique_exacte_avec_marque_reste_admise(marque):
    texte = f"Valeur 8{marque}400.00"
    assert conseil.chiffres_libres(texte, [texte]) == []
    assert rg.nombres_libres(texte, [texte]) == []


def test_dates_et_plages_marquees_ne_sont_jamais_normalisees():
    date = "Date 2026-11-\u200b09"
    plage = "Plage 1\u200b-2"
    assert conseil.chiffres_libres(date, [date]) == []
    assert rg.nombres_libres(date, [date]) == []
    assert conseil.chiffres_libres(plage, [plage]) == []
    assert rg.nombres_libres(plage, [plage]) == []
    assert conseil.chiffres_libres("Date 2026-11-\u200b10", [date])
    assert rg.nombres_libres("Date 2026-11-\u200b10", [date])
    assert conseil.chiffres_libres("Plage 1\u200b-3", [plage])
    assert rg.nombres_libres("Plage 1\u200b-3", [plage])


def test_identifiant_et_emojis_isoles_ne_sont_pas_recomposes():
    identifiant = "Code: 8\u200b400"
    assert conseil.chiffres_libres(identifiant, [identifiant]) == []
    assert rg.nombres_libres(identifiant, [identifiant]) == []
    assert conseil.chiffres_libres("Équipe 👩🏽‍💻 café\u0301", []) == []
    assert rg.nombres_libres("Équipe 👩🏽‍💻 café\u0301", []) == []
    assert conseil.chiffres_libres("Score 8️⃣", []) == []
    assert rg.nombres_libres("Score 8️⃣", ["8️⃣"]) == []
    assert conseil.chiffres_libres("Réf\u200b2", []) == []
    assert rg.nombres_libres("Réf\u200b2", ["2"]) == []
    identifiant_marque = "Option option\u200b-2"
    assert conseil.chiffres_libres(identifiant_marque, [identifiant_marque]) == []
    assert rg.nombres_libres(identifiant_marque, [identifiant_marque]) == []
    commande = "Run: outil --count 8\u200b400"
    assert conseil.chiffres_libres(commande, [commande]) == []
    assert rg.nombres_libres(commande, [commande]) == []


@pytest.mark.parametrize("marque", MARQUES)
def test_sans_source_les_nombres_marques_restent_refuses(marque):
    texte = f"Gain 8{marque}400.00 $"
    assert conseil.chiffres_libres(texte, [])
    assert rg.nombres_libres(texte, [])


@pytest.mark.parametrize("source", ["8\u200b400.00 $", "-\u200b8400.00 $"])
def test_admission_conseil_ne_tire_pas_de_fragment_dune_source_marquee(source):
    sortie = {
        "affirmations": [
            {"id": "O1", "nature": "observation_source", "reference": "r1", "valeur": source},
            {"id": "H1", "nature": "hypothese", "enonce": "Gain 400.00 $"},
        ]
    }
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        conseil.admettre_proposition(sortie, sources={"r1": source})


@pytest.mark.parametrize("source", ["8\u200b400.00 $", "-\u200b8400.00 $"])
def test_recommandation_ne_tire_pas_de_fragment_dune_source_marquee(source, monkeypatch):
    reco = reco_tests.reco_valide()
    adresse = reco["chiffres"][0]["source"]["adresse"]
    reco["chiffres"][0]["valeur"] = source
    reco["options"][0]["description"] = "Gain 400.00 $"
    monkeypatch.setitem(reco_tests.FAITS, adresse, source)

    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        reco_tests.controler(reco)


@pytest.mark.parametrize("api", ["conseil", "recommandation"])
def test_citation_complete_marquee_reste_admise(api, monkeypatch):
    source = "8\u200b400.00 $"
    if api == "conseil":
        sortie = {
            "affirmations": [
                {"id": "O1", "nature": "observation_source", "reference": "r1", "valeur": source},
                {"id": "H1", "nature": "hypothese", "enonce": f"Gain {source}"},
            ]
        }
        assert conseil.admettre_proposition(sortie, sources={"r1": source})["type"] == "PROPOSITION_ADMISE"
        return

    reco = reco_tests.reco_valide()
    adresse = reco["chiffres"][0]["source"]["adresse"]
    reco["chiffres"][0]["valeur"] = source
    reco["options"][0]["description"] = f"Gain {source}"
    monkeypatch.setitem(reco_tests.FAITS, adresse, source)
    assert reco_tests.controler(reco)["valide"]


def test_source_date_marquee_et_montant_distinct_reste_localise():
    source = "Date 2026-11-\u200b09; montant 400.00 $"
    assert conseil.chiffres_libres("Montant 400.00 $", [source]) == []
    assert rg.nombres_libres("Montant 400.00 $", [source]) == []

    sortie = {
        "affirmations": [
            {"id": "O1", "nature": "observation_source", "reference": "r1", "valeur": source},
            {"id": "H1", "nature": "hypothese", "enonce": "Montant 400.00 $"},
        ]
    }
    assert conseil.admettre_proposition(sortie, sources={"r1": source})["type"] == "PROPOSITION_ADMISE"


def test_recommandation_conserve_montant_distinct_dune_source_date_marquee(monkeypatch):
    source = "Date 2026-11-\u200b09; montant 400.00 $"
    reco = reco_tests.reco_valide()
    adresse = reco["chiffres"][0]["source"]["adresse"]
    reco["chiffres"][0]["valeur"] = source
    reco["options"][0]["description"] = "Montant 400.00 $"
    monkeypatch.setitem(reco_tests.FAITS, adresse, source)
    assert reco_tests.controler(reco)["valide"]


@pytest.mark.parametrize(
    "source",
    [
        "Montant 8\u200b 400,00 $",
        "Montant 8 \u200b400,00 $",
        "Montant 8 400,\u200b00 $",
        "Montant 8 400,00\u200b $",
    ],
)
def test_source_montant_groupe_marque_ne_permet_pas_forme_nette(source, monkeypatch):
    sortie = {
        "affirmations": [
            {"id": "O1", "nature": "observation_source", "reference": "r1", "valeur": source},
            {"id": "H1", "nature": "hypothese", "enonce": "Montant 8400.00 $"},
        ]
    }
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        conseil.admettre_proposition(sortie, sources={"r1": source})

    reco = reco_tests.reco_valide()
    adresse = reco["chiffres"][0]["source"]["adresse"]
    reco["chiffres"][0]["valeur"] = source
    reco["options"][0]["description"] = "Montant 8400.00 $"
    monkeypatch.setitem(reco_tests.FAITS, adresse, source)
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        reco_tests.controler(reco)


def test_montant_groupe_marque_exactement_cite_reste_admis():
    texte = "Montant 8\u200b 400,00 $"
    assert conseil.chiffres_libres(texte, [texte]) == []
    assert rg.nombres_libres(texte, [texte]) == []


@pytest.mark.parametrize("categorie", ["\u200b", "\u0307", "\u0903", "\u20dd"])
@pytest.mark.parametrize("nombre", ["1", "12", "1.2", "8400.00"])
@pytest.mark.parametrize("api", ["conseil", "recommandation"])
def test_source_numerique_marquee_ne_permet_pas_son_equivalent_net(categorie, nombre, api, monkeypatch):
    insertion = min(len(nombre), 1)
    nombre_marque = nombre[:insertion] + categorie + nombre[insertion:]
    source = f"Montant {nombre_marque} $"
    texte_net = f"Montant {nombre} $"

    if api == "conseil":
        sortie = {
            "affirmations": [
                {"id": "O1", "nature": "observation_source", "reference": "r1", "valeur": source},
                {"id": "H1", "nature": "hypothese", "enonce": texte_net},
            ]
        }
        with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
            conseil.admettre_proposition(sortie, sources={"r1": source})
        return

    reco = reco_tests.reco_valide()
    adresse = reco["chiffres"][0]["source"]["adresse"]
    reco["chiffres"][0]["valeur"] = source
    reco["options"][0]["description"] = texte_net
    monkeypatch.setitem(reco_tests.FAITS, adresse, source)
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        reco_tests.controler(reco)


@pytest.mark.parametrize("marque", ["\u200b", "\u0307", "\u0903", "\u20dd"])
@pytest.mark.parametrize("signe", SIGNES)
@pytest.mark.parametrize("index_forme", range(5))
@pytest.mark.parametrize("api", ["conseil", "recommandation"])
def test_source_negative_marquee_ne_permet_pas_le_montant_positif(
    marque, signe, index_forme, api, monkeypatch
):
    forme_negative = _formes_signe_devise(signe, marque)[index_forme]
    source = f"Perte {forme_negative}"
    texte_positif = "Valeur positive 8400.00 $"

    if api == "conseil":
        sortie = {
            "affirmations": [
                {"id": "O1", "nature": "observation_source", "reference": "r1", "valeur": source},
                {"id": "H1", "nature": "hypothese", "enonce": texte_positif},
            ]
        }
        with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
            conseil.admettre_proposition(sortie, sources={"r1": source})
        return

    reco = reco_tests.reco_valide()
    adresse = reco["chiffres"][0]["source"]["adresse"]
    reco["chiffres"][0]["valeur"] = source
    reco["options"][0]["description"] = texte_positif
    monkeypatch.setitem(reco_tests.FAITS, adresse, source)
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        reco_tests.controler(reco)


def test_sequence_longue_est_emise_une_fois_et_borne_exactement_a_max_texte():
    texte = "Gain " + "8" + "\u200b" * 1486 + "400.00 $"
    assert len(texte) == conseil.MAX_TEXTE
    token = texte.removeprefix("Gain ")
    cites = ["400.00 $"]
    assert conseil.chiffres_libres(texte, cites) == [token]
    assert rg.nombres_libres(texte, ["8", "400.00"]) == [token]

    exact = [texte]
    assert conseil.chiffres_libres(texte, exact) == []
    assert rg.nombres_libres(texte, exact) == []


def test_citations_nombreuses_et_token_tronque_restent_bornes_et_refuses():
    texte = "Gain " + "8" + "\u200b" * 1486 + "400.00 $"
    citations = [
        f"aucune valeur {index} " + "x" * (conseil.MAX_TEXTE - len(f"aucune valeur {index} "))
        for index in range(48)
    ]
    assert all(len(citation) == conseil.MAX_TEXTE for citation in citations)
    conseil_resultat = conseil.chiffres_libres(texte, citations)
    reco_resultat = rg.nombres_libres(texte, citations)
    assert len(conseil_resultat) <= 2 and len(reco_resultat) <= 3
    assert any(len(token) > 1000 for token in conseil_resultat)
    assert any(len(token) > 1000 for token in reco_resultat)

    trop_long = "Gain " + "8" + "\u200b" * 1500 + "400.00 $"
    assert len(trop_long) > conseil.MAX_TEXTE
    assert conseil.chiffres_libres(trop_long, [trop_long])
    assert rg.nombres_libres(trop_long, [trop_long])


@pytest.mark.parametrize("signe", SIGNES)
@pytest.mark.parametrize("marque", MARQUES_SIGNE)
def test_marque_ne_casse_pas_signe_devise_mais_refuse_une_citation_positive(signe, marque, monkeypatch):
    for forme_negative in _formes_signe_devise(signe, marque):
        assert conseil.chiffres_libres("Perte " + forme_negative, ["8400.00 $"])
        assert rg.nombres_libres("Perte " + forme_negative, ["8400.00"])
        assert conseil.chiffres_libres("Perte " + forme_negative, [forme_negative]) == []
        assert rg.nombres_libres("Perte " + forme_negative, [forme_negative]) == []

        sortie = {
            "affirmations": [
                {"id": "O1", "nature": "observation_source", "reference": "r1", "valeur": forme_negative},
                {"id": "H1", "nature": "hypothese", "enonce": "Perte " + forme_negative},
            ]
        }
        assert conseil.admettre_proposition(sortie, sources={"r1": forme_negative})["type"] == "PROPOSITION_ADMISE"

        reco = reco_tests.reco_valide()
        adresse = reco["chiffres"][0]["source"]["adresse"]
        reco["chiffres"][0]["valeur"] = "8400.00"
        monkeypatch.setitem(reco_tests.FAITS, adresse, "8400.00")
        reco["options"][0]["description"] = "Perte " + forme_negative
        with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
            reco_tests.controler(reco)


def test_un_tiret_espace_reste_une_ponctuation_et_ne_devient_pas_un_signe():
    texte = "Total - 8 400,00 $"
    assert conseil.chiffres_libres(texte, ["8400.00"]) == []
    assert rg.nombres_libres(texte, ["8400.00"]) == []
    texte_invisible_apres_tiret_espace = "Total - \u200b 8 400,00 $"
    assert conseil.chiffres_libres(texte_invisible_apres_tiret_espace, ["8400.00"]) == []
    assert rg.nombres_libres(texte_invisible_apres_tiret_espace, ["8400.00"]) == []


@pytest.mark.parametrize("signe", SIGNES)
@pytest.mark.parametrize("marque", ["\u200b", "\u0307", "\u0903", "\u20dd"])
@pytest.mark.parametrize("nombre", ["1", "12", "1.2", "8400.00"])
def test_matrice_signes_marques_et_precisions(signe, marque, nombre, monkeypatch):
    source_positive = f"{nombre} $"
    for forme_negative in _formes_signe_devise(signe, marque, nombre):
        texte = "Perte " + forme_negative
        assert conseil.chiffres_libres(texte, [])
        assert rg.nombres_libres(texte, [])
        assert conseil.chiffres_libres(texte, [source_positive])
        assert rg.nombres_libres(texte, [nombre])

        sortie = {
            "affirmations": [
                {"id": "O1", "nature": "observation_source", "reference": "r1", "valeur": source_positive},
                {"id": "H1", "nature": "hypothese", "enonce": texte},
            ]
        }
        with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
            conseil.admettre_proposition(sortie, sources={"r1": source_positive})

        reco = reco_tests.reco_valide()
        adresse = reco["chiffres"][0]["source"]["adresse"]
        reco["chiffres"][0]["valeur"] = nombre
        with monkeypatch.context() as contexte:
            contexte.setitem(reco_tests.FAITS, adresse, nombre)
            reco["options"][0]["description"] = texte
            with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
                reco_tests.controler(reco)

        reco_citee = reco_tests.reco_valide()
        adresse_citee = reco_citee["chiffres"][0]["source"]["adresse"]
        reco_citee["chiffres"][0]["valeur"] = forme_negative
        reco_citee["options"][0]["description"] = texte
        with monkeypatch.context() as contexte:
            contexte.setitem(reco_tests.FAITS, adresse_citee, forme_negative)
            assert reco_tests.controler(reco_citee)["valide"]

        assert conseil.chiffres_libres(texte, [forme_negative]) == []
        assert rg.nombres_libres(texte, [forme_negative]) == []


@pytest.mark.parametrize("marque", ["\u0307", "\u0903", "\u20dd"])
def test_marque_combinante_sur_un_chiffre_isole_exige_la_citation_exacte(marque):
    texte = f"Valeur 1{marque} $"
    assert conseil.chiffres_libres(texte, ["1 $"])
    assert rg.nombres_libres(texte, ["1"])
    assert conseil.chiffres_libres(texte, [texte]) == []
    assert rg.nombres_libres(texte, [texte]) == []


def test_un_token_marque_dans_un_identifiant_ne_vaut_pas_citation_exacte_conseil():
    source = "Code8\u200b400X"
    sortie = {"affirmations": [
        {"id": "O1", "nature": "observation_source", "reference": "r1", "valeur": source},
        {"id": "H1", "nature": "hypothese", "enonce": "Gain 8\u200b400"},
    ]}
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        conseil.admettre_proposition(sortie, sources={"r1": source})


def test_un_token_marque_dans_un_identifiant_ne_vaut_pas_citation_exacte_reco():
    source = "Code8\u200b400X"
    reco = reco_tests.reco_valide()
    adresse = reco["chiffres"][0]["source"]["adresse"]
    reco["chiffres"][0]["valeur"] = source
    reco["options"][0]["description"] = "Gain 8\u200b400"
    faits = dict(reco_tests.FAITS)
    faits[adresse] = source
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        rg.controler(
            reco, faits=faits, certitudes=reco_tests.CERTITUDES,
            recus={reco_tests.EMPREINTE_RECU: reco_tests.recu_factice()},
            verifier_recu=reco_tests.verifier_ok,
        )
