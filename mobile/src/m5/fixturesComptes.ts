/** Formes métier fictives dérivées des modules purs M5 en RAM ; enveloppes HTTP qualifiées séparément. */
export const FICTIF = true;
export const JOUR = "2026-09-02";
export const creances = {
  role: "admin", factures: [{ facture_id: "FACT-ENVOYEE", chantier_id: "CH-D2", devis_id: "D2", client_id: "CLIENT-1-fictif",
    montant_apres_taxes: "689.85", date_envoi: "2026-08-03T00:00:00+00:00" }],
  nombre: 1, total_a_recevoir: "689.85", total_complet: true, illisibles: [],
  age: { aujourd_hui: JOUR, tranches: {
    "0-30": [{ facture_id: "FACT-ENVOYEE", client_id: "CLIENT-1-fictif", montant_apres_taxes: "689.85", date_envoi: "2026-08-03", age_jours: 30 }],
    "31-60": [], "61-90": [], "90+": [],
  }, total_par_tranche: { "0-30": "689.85", "31-60": "0", "61-90": "0", "90+": "0" }, exclues: [] }, age_non_calcule: null,
};
export const ap = {
  role: "admin", type: "COMPTES_A_PAYER", mention: "Analyse préparatoire IA — validation humaine requise.",
  ordre: "ordre des réceptions", hypotheses: ["Unité de prix à confirmer par le propriétaire."],
  taxes_versions: { tps_federale: "2026-v1", tvq_quebec: "2026-v1" },
  total: 1, depart: 0, affichees: 1, reste: 0, prochain_depart: null, message: null,
  totaux: { nombre_po: 1, attendu_apres_taxes: "344.93", facture_apres_taxes: "0.00",
    a_payer_apres_taxes: "344.93", a_payer_connu_apres_taxes: "344.93", complet: true, non_calculables: 0, non_calculables_po: [] },
  comptes: [{ po_id: "PO-1", fournisseur_id: "gentek", chantier_id: "CH-1", statut_po: "partially_received",
    receptions: 1, derniere_reception: "2026-09-29T09:15:00-04:00",
    attendu: { avant_taxes: "300.00", taxes: "44.93", apres_taxes: "344.93" },
    factures: { nombre: 0, avant_taxes: "0.00", taxes: "0.00", apres_taxes: "0.00" }, a_payer_apres_taxes: "344.93",
    rapprochement: { statut: "PROPOSE", verdict: "SANS_FACTURE", facture_avant_taxes: null } }],
};
export const sansPO = {
  role: "admin", type: "COMPTES_A_PAYER_SANS_PO", mention: ap.mention,
  ordre: "ordre de saisie", hypotheses: ["Factures sans commande vivantes."],
  totaux: { nombre: 1, avant_taxes: "100.00", taxes: "14.98", apres_taxes: "114.98", par_categorie: {} },
  total: 1, depart: 0, affichees: 1, reste: 0, prochain_depart: null, message: null,
  factures: [{ facture_fournisseur_id: "AP-FICTIVE", numero_facture: "C-4001", date_facture: "2026-10-01",
    avant_taxes: "100.00", taxes: "14.98", apres_taxes: "114.98", statut: "SAISIE",
    saisi_par: "admin.fictif", avertissements: [], fournisseur_id: "Pétro-Nord (fictif)", categorie_depense: "carburant" }],
};
export const attentes = { attentes_devis: [{ devis_id: "D-WCT-FICTIF", statut: "en_attente_travaux_termines" }],
  attentes_wct_sans_devis_id: [{ wct_id: "WCT-FICTIF", intervention_id: "I-FICTIF", statut: "wct_sans_devis_id" }] };
