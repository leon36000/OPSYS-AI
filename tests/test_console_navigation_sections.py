from opsys.console.pages import ONGLETS, Session, gabarit


def test_navigation_sections_preserve_liens_et_etat_courant_avec_repli_progressif():
    html = gabarit(
        "Départements",
        "Contenu fictif",
        prefixe="/opsys",
        session=Session("admin.fictif", frozenset({"admin"}), "csrf-fictif", 4102444800),
        actif="departements",
    )

    assert html.count('aria-current="page"') == 1
    assert 'href="/opsys/departements" aria-current="page">Départements' in html
    assert html.count('href="/opsys/') >= len(ONGLETS)
    assert 'aria-controls="navigation-sections"' in html
    assert '<nav id="navigation-sections" aria-label="Sections">' in html
    assert (
        'class="bouton-sections" aria-controls="navigation-sections" '
        'aria-expanded="true" hidden>Sections</button>'
    ) in html


def test_console_js_replie_uniquement_apres_chargement_et_supporte_escape():
    from opsys.console.ressources import CSS, JS

    assert 'navigationSections.hidden = true' in JS
    assert 'navigationSections.hidden = false' in JS
    assert 'evenement.key === "Escape"' in JS
    assert 'navigationSections.contains(document.activeElement)' in JS
    assert 'document.activeElement === boutonSections' in JS
    assert 'if (navigationSections.contains(elementFocalise)) boutonSections.focus()' in JS
    assert 'if (elementFocalise === boutonSections)' in JS
    assert 'boutonSections.focus()' in JS
    assert 'premierLien.focus()' in JS
    assert '.bouton-sections:focus:not([hidden]) { display: inline-block; }' in CSS

