import fs from "node:fs";
import path from "node:path";

import { interpreterResultatClient360, interpreterResultatClientDeLead, interpreterResultatSuggestion } from "../m2/client360";
import { interpreterResultatEnregistrerInteraction } from "../m2/interaction";
import { interpreterResultatListerLeads } from "../m2/listeLeads";
import { interpreterResultatLireDevis } from "../m3/devis";
import { devisCitesParLeads } from "./devisConnus";
import { historiqueDuLead } from "./fiche";

/**
 * Les VRAIES réponses du moteur (`fixtures/reponses-moteur.json`), passées par les lecteurs de l'app. Ce fichier n'est
 * pas écrit à la main : `tests/e2e/test_vendeur_appareil.py` (`test_les_reponses_du_moteur_ont_la_forme_de_la_fixture...`)
 * compare la forme des réponses d'un vrai moteur à celle de la fixture, et échoue si elles divergent. Ces tests-ci
 * prouvent l'autre moitié : les lecteurs de l'app comprennent cette forme. Données fictives (`fictif: true`).
 */
interface Fixture {
  readonly fictif: boolean;
  readonly reponses: Readonly<Record<string, unknown>>;
}

const fixture: Fixture = JSON.parse(
  fs.readFileSync(path.join(__dirname, "fixtures", "reponses-moteur.json"), "utf8"),
) as Fixture;
const reponse = (nom: string): unknown => {
  const trouve = fixture.reponses[nom];
  if (trouve === undefined) {
    throw new Error(`la fixture n'a pas « ${nom} »`);
  }
  return trouve;
};

describe("la fixture des réponses du moteur", () => {
  test("est marquée fictive, avec ses quinze réponses", () => {
    expect(fixture.fictif).toBe(true);
    expect(Object.keys(fixture.reponses)).toHaveLength(15);
  });
});

describe("m2_lister_leads, tel que le moteur le rend", () => {
  test("la liste du vendeur : quatre leads, leurs segments avec règle citée, les segments non calculables et leur manque", () => {
    const lecture = interpreterResultatListerLeads(reponse("page_des_leads"));
    expect(lecture.ok).toBe(true);
    if (!lecture.ok) {
      return;
    }
    const { page } = lecture;
    expect(page.leads.map((l) => l.leadId)).toEqual(["lead-a-1", "lead-a-2", "lead-a-3", "lead-a-4"]);
    expect([page.total, page.decalage, page.reste, page.suivant, page.illisibles]).toEqual([4, 0, 0, null, 0]);
    const urgent = page.leads[0];
    expect(urgent.urgenceDeclaree).toBe(true);
    expect(urgent.segments.map((s) => [s.segment, s.regle])).toEqual([
      ["hot_lead", "urgence_declaree_lead_ouvert"],
      ["estimate_ready", "readiness_m3_satisfaite"],
    ]);
    expect(Object.keys(page.regles).sort()).toEqual([
      "readiness_m3_satisfaite",
      "soumission_acceptee_a_planifier",
      "urgence_declaree_lead_ouvert",
    ]);
    // Les segments non calculables gardent leur « manque X » : les six sans donnée, et les deux seuils à configurer.
    expect(page.segmentsNonCalculables.map((n) => n.segment)).toEqual([
      "needs_photos",
      "quote_sent",
      "quote_stale",
      "high_value_customer",
      "referral_candidate",
      "complaint_risk",
      "dormant_lead",
      "seasonal_opportunity",
    ]);
    expect(page.segmentsNonCalculables.find((n) => n.segment === "quote_stale")?.manque).toContain("seuil à configurer");
    expect(page.leads.every((l) => l.proprietaire === "vendeur.a")).toBe(true);
  });

  test("le lead converti cite le devis accepté : la seule source de numéro de devis de l'écran des soumissions", () => {
    const lecture = interpreterResultatListerLeads(reponse("page_du_segment_converti"));
    expect(lecture.ok && lecture.page.filtre).toEqual({ statut: null, segment: "won_pending_schedule" });
    expect(lecture.ok && devisCitesParLeads(lecture.page.leads)).toEqual([
      { devisId: "devis-a-2", leadId: "lead-a-2", origine: "lead_converti" },
    ]);
  });

  test("le refus d'un segment non calculable garde son code et son « manque X » : genre refus", () => {
    const lecture = interpreterResultatListerLeads(reponse("refus_segment_non_calculable"));
    expect(lecture).toMatchObject({ ok: false, genre: "refus", verdict: { code: "REJ-SEGMENT-NON-CALCULABLE" } });
    expect(!lecture.ok && lecture.verdict.detail).toContain("non calculable, manque");
  });

  test("un argument inconnu : refus technique du socle, lu comme un refus de la requête (jamais un succès, jamais un cache)", () => {
    expect(interpreterResultatListerLeads(reponse("arguments_invalides"))).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code: "arguments_invalides", detail: "paramètre inconnu : owner" },
    });
  });
});

describe("la fiche du lead, telle que le moteur la rend", () => {
  test("la règle citée, son texte fixe et son motif : la règle du doublon en attente, puis celle du dossier prêt", () => {
    const doublon = interpreterResultatSuggestion(reponse("suggestion_doublon"));
    expect(doublon.ok && [doublon.valeur.regle, doublon.valeur.statut]).toEqual(["doublon_en_attente", "qualifie"]);
    expect(doublon.ok && doublon.valeur.suggestion).toMatch(/^Arbitrer le doublon [0-9a-f]{64} avant de poursuivre\.$/);
    const prete = interpreterResultatSuggestion(reponse("suggestion_prete"));
    expect(prete.ok && prete.valeur).toMatchObject({
      leadId: "lead-a-4",
      regle: "transmettre_m3",
      suggestion: "Transmettre le dossier à M3 pour estimation.",
    });
  });

  test("le lead d'un autre vendeur : le refus du serveur, jamais une suggestion", () => {
    expect(interpreterResultatSuggestion(reponse("refus_lead_d_un_autre"))).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "ce lead n'est pas assigné à la personne authentifiée (ou est inconnu)" },
    });
  });

  test("le client du lead, puis son Client 360 : contact, ses opportunités seulement, l'historique de CE lead", () => {
    const lien = interpreterResultatClientDeLead(reponse("client_du_lead"));
    expect(lien.ok && lien.valeur.leadId).toBe("lead-a-1");
    const vue = interpreterResultatClient360(reponse("client_360"));
    expect(vue.ok).toBe(true);
    if (!vue.ok || !lien.ok) {
      return;
    }
    expect(vue.valeur.clientId).toBe(lien.valeur.clientId);
    expect(vue.valeur.contact).toEqual({ nom: "Cliente Partagée (fictif)", courriel: "partagee@exemple-fictif.test" });
    expect(vue.valeur.opportunites.map((o) => [o.leadId, o.statut, o.typeTravaux, o.service])).toEqual([
      ["lead-a-1", "qualifie", "renovation_totale", null],
      ["lead-a-2", "converti", "renovation_totale", null],
    ]);
    expect(vue.valeur.illisibles).toBe(0);
    const historique = historiqueDuLead(vue.valeur, "lead-a-1");
    expect(historique.interactions.map((i) => [i.auteur, i.systeme])).toEqual([["vendeur.a", false]]);
    expect(historique.interactions[0].resume).toBe("Premier appel : le client veut voir le devis (fictif)");
  });
});

describe("m3_lire_devis, tel que le moteur le rend au vendeur : la vue interne, réduite à sa liste blanche", () => {
  test("la réponse porte coût et marge (la vue interne) ; l'app n'en garde aucun, seulement statut et prix", () => {
    const brut = JSON.stringify(reponse("devis_interne"));
    for (const present of ["cout_total", "taux_marge", "cout_unitaire", "cout_ligne"]) {
      expect(brut).toContain(present); // sans cela, ce test ne prouverait rien
    }
    const lecture = interpreterResultatLireDevis(reponse("devis_interne"));
    expect(lecture.ok).toBe(true);
    if (!lecture.ok) {
      return;
    }
    expect(lecture.devis).toMatchObject({
      devisId: "devis-a-2",
      leadId: "lead-a-2",
      statut: "brouillon",
      prixTotal: "360.00",
      chantierId: null,
    });
    expect(lecture.devis.lignes[0]).toMatchObject({ quantite: "30", unite: "pi_lin", prixUnitaire: "12.00", prixLigne: "360.00" });
    const garde = JSON.stringify(lecture.devis);
    for (const interdit of ["cout", "marge", "taux", "300.00", "10.00", "0.20", "besoin-goutt"]) {
      expect(garde).not.toContain(interdit);
    }
  });

  test("le devis d'un autre vendeur : le refus d'un devis inconnu, tel quel", () => {
    expect(interpreterResultatLireDevis(reponse("refus_devis_d_un_autre"))).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code: "REJ-DEVIS-INTROUVABLE", detail: "devis inconnu : 'devis-b-1'" },
    });
  });
});

describe("m2_enregistrer_interaction, tel que le moteur le rend", () => {
  test("note enregistrée, puis rejouée avec la même clé : le même accusé, jamais un second effet", () => {
    const premiere = interpreterResultatEnregistrerInteraction(reponse("note_enregistree"));
    const rejeu = interpreterResultatEnregistrerInteraction(reponse("note_rejouee"));
    expect(premiere.accepte).toBe(true);
    expect(rejeu).toEqual(premiere);
    expect(premiere.accepte && premiere.resultat).toMatchObject({ leadId: "lead-a-3", horodatage: "2026-09-29T12:00:00-04:00" });
    expect(premiere.accepte && premiere.resultat.ligneId).toMatch(/^[0-9a-f]{64}$/);
    expect((reponse("note_rejouee") as { rejoue: boolean }).rejoue).toBe(true);
    expect((reponse("note_enregistree") as { rejoue: boolean }).rejoue).toBe(false);
  });

  test("même clé, autre contenu : le conflit du socle, lu comme un refus (échec permanent, jamais un succès)", () => {
    const conflit = interpreterResultatEnregistrerInteraction(reponse("note_conflit"));
    expect(conflit).toMatchObject({ accepte: false, verdict: { code: "mutation_conflit" } });
  });

  test("le lead d'un autre vendeur : le refus du serveur, tel quel", () => {
    expect(interpreterResultatEnregistrerInteraction(reponse("note_refusee"))).toEqual({
      accepte: false,
      verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "ce lead n'est pas assigné à la personne authentifiée (ou est inconnu)" },
    });
  });
});
