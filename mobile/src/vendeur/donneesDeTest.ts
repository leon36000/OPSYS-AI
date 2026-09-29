/**
 * Données FICTIVES des tests du profil vendeur (AGENTS.md : « les fixtures portent fictif »). Elles reprennent la
 * forme EXACTE que le serveur rend (`liste_leads.py`, `clients.py`, `suggestions.py`, `devis_durable.py`) ; la
 * forme d'une vraie réponse du moteur est comparée à `tests/fixtures/contrats_mobile_vendeur.json` par
 * `tests/e2e/test_vendeur_appareil.py`. Aucun test n'importe ce fichier hors de `src/` : ce n'est pas du code
 * de production.
 */

export const FICTIF = true;

export const SEGMENT_URGENT = {
  segment: "hot_lead",
  regle: "urgence_declaree_lead_ouvert",
  donnee: { urgence_declaree: true, statut: "qualifie" },
};

export const REGLES_FICTIVES: Record<string, string> = {
  urgence_declaree_lead_ouvert:
    "Urgence déclarée à l'ingestion (contrat : urgence_declaree) sur un lead encore ouvert (statut nouveau ou qualifie).",
  soumission_acceptee_a_planifier:
    "Lead converti : la soumission est acceptée et le chantier reste à planifier par M4 (règle planifier_chantier).",
};

export const NON_CALCULABLES_FICTIFS = [
  { segment: "needs_photos", manque: "non calculable, manque l'état des photos du lead (M3 les qualifie, rien n'atteint M2)" },
  { segment: "dormant_lead", manque: "non calculable, manque le seuil jours_inactivite_dormant : seuil à configurer" },
];

export function leadBrut(leadId: string, surcharges: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    lead_id: leadId,
    statut: "qualifie",
    proprietaire: "vendeur.fictif",
    travaux: "renovation_totale",
    ville: "Repentigny",
    urgence_declaree: false,
    ingere_le: "2026-09-01T09:00:00-04:00",
    derniere_activite: "2026-09-02T09:00:00-04:00",
    prochaine_action: { description: "Appeler le client (fictif)", echeance: "2026-09-05T09:00:00-04:00" },
    segments: [],
    ...surcharges,
  };
}

export interface OptionsPageBrute {
  readonly leads: readonly Record<string, unknown>[];
  readonly decalage?: number;
  readonly total?: number;
  readonly reste?: number;
  readonly suivant?: number | null;
  readonly filtre?: { statut: string | null; segment: string | null };
  readonly regles?: Record<string, string>;
  readonly nonCalculables?: readonly { segment: string; manque: string }[];
  readonly indetermines?: number;
}

/** Une page de `m2_lister_leads` (le `R` de l'enveloppe), cohérente par défaut : rien ne suit. */
export function pageBrute(options: OptionsPageBrute): Record<string, unknown> {
  const decalage = options.decalage ?? 0;
  const affichees = options.leads.length;
  const total = options.total ?? decalage + affichees;
  const reste = options.reste ?? Math.max(0, total - decalage - affichees);
  return {
    ordre: "ingestion croissante (le plus ancien d'abord, instants comparés en UTC), puis lead_id croissant",
    filtre: options.filtre ?? { statut: null, segment: null },
    total,
    decalage,
    affichees,
    reste,
    suivant: options.suivant !== undefined ? options.suivant : reste > 0 ? decalage + affichees : null,
    message: null,
    indetermines: options.indetermines ?? 0,
    leads: options.leads,
    regles: options.regles ?? {},
    segments_non_calculables: options.nonCalculables ?? [],
  };
}

/** L'enveloppe d'une réponse acceptée d'outil : ce que `invoquerOutil` rend dans `result`. */
export function enveloppeAcceptee(valeur: unknown): Record<string, unknown> {
  return { ok: true, resultat: { accepte: true, resultat: valeur }, rejoue: false };
}

export function enveloppeRefusee(code: string, detail = ""): Record<string, unknown> {
  return { ok: true, resultat: { accepte: false, verdict: { code, statut: "", detail } } };
}

export const SUGGESTION_BRUTE = {
  lead_id: "lead-a-01",
  statut: "qualifie",
  regle: "transmettre_m3",
  suggestion: "Transmettre le dossier à M3 pour estimation.",
  motif: "Readiness M3 satisfaite (M2.5) : owner, type de travaux, ville, interaction post-qualification.",
};

export const CLIENT_DE_LEAD_BRUT = { lead_id: "lead-a-01", client_id: "a2f9b5d094369843521d099715b97ef817491c0e2309406bd46d75c41301a346" };

export function client360Brut(surcharges: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    client_id: "a2f9b5d094369843521d099715b97ef817491c0e2309406bd46d75c41301a346",
    contact: { nom: "Cliente Fictive", courriel: "cliente@exemple-fictif.test" },
    opportunites: [
      {
        lead_id: "lead-a-01",
        statut: "qualifie",
        ville: "Repentigny",
        type_travaux: "renovation_totale",
        service: null,
        canal: "telephone",
        source: null,
        campagne: null,
        utm: null,
        prochaine_action: { description: "Appeler le client (fictif)", echeance: "2026-09-05T09:00:00-04:00" },
      },
      {
        lead_id: "lead-a-02",
        statut: "avis",
        ville: "Repentigny",
        type_travaux: null,
        service: "gouttieres",
        canal: "telephone",
        source: null,
        campagne: null,
        utm: null,
        prochaine_action: null,
      },
    ],
    interactions_recentes: [
      { lead_id: "lead-a-02", auteur: "vendeur.fictif", resume: "Appel de suivi (fictif)", horodatage: "2026-09-03T10:00:00-04:00" },
      { lead_id: "lead-a-01", auteur: "vendeur.fictif", resume: "Premier appel (fictif)", horodatage: "2026-09-04T10:00:00-04:00" },
      { lead_id: "lead-a-01", auteur: "system:m3", resume: "Relancer le client (fictif)", horodatage: "2026-09-05T10:00:00-04:00" },
    ],
    ...surcharges,
  };
}

/** Un devis tel que la vue « interne » de M3 le rend AU VENDEUR : avec coût et marge, que l'app n'affiche ni ne
 * garde. */
export function devisInterneBrut(devisId: string, surcharges: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    type_entree: "devis_cree",
    devis_id: devisId,
    lead_id: "lead-a-01",
    chantier_id: null,
    lignes: [
      {
        reference_ligne: `${devisId}-L0`,
        description: "Gouttière alu 5 po (fictif)",
        quantite: "30",
        unite: "pi_lin",
        cout_unitaire: "10.00",
        reference_besoin_materiau: "besoin-goutt-001",
        cout_ligne: "300.00",
        prix_unitaire: "12.00",
        prix_ligne: "360.00",
      },
    ],
    taux_marge: "0.20",
    cout_total: "300.00",
    prix_total: "360.00",
    statut: "brouillon",
    horodatage: "2026-09-01T09:05:00-04:00",
    ...surcharges,
  };
}

export const ACCUSE_NOTE_BRUT = {
  lead_id: "lead-a-01",
  ligne_id: "a3f1c2d4e5b6a7980123456789abcdef0123456789abcdef0123456789abcdef",
  tete_chaine: "b4e2d3c5f6a7b8091234567890abcdef1234567890abcdef1234567890abcdef",
  horodatage: "2026-09-29T14:03:22-04:00",
};

/** Un faux transport de `/tools/invoke` : un gestionnaire par outil, qui rend l'enveloppe (`result`) ou lève. */
export function fauxTransport(
  gestionnaires: Record<string, (args: Record<string, unknown>) => unknown>,
): jest.Mock {
  return jest.fn(async (params: { requete: { tool: string; args?: Record<string, unknown> } }) => {
    const gestionnaire = gestionnaires[params.requete.tool];
    if (gestionnaire === undefined) {
      return {
        ok: false,
        echec: {
          origine: "http",
          reessayable: false,
          message: `outil hors portée : ${params.requete.tool}`,
          status: 403,
          erreur: { type: "tool_call_blocked", message: `OPSYS device is not authorized to call "${params.requete.tool}".` },
        },
      };
    }
    return { ok: true, result: gestionnaire(params.requete.args ?? {}) };
  });
}

/** Le transport tombe : aucune réponse (hors ligne). */
export function transportHorsLigne(): jest.Mock {
  return jest.fn(async () => ({
    ok: false,
    echec: { origine: "reseau", reessayable: true, message: "Network request failed" },
  }));
}
