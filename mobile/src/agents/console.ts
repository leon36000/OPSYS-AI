/** Client séparé pour la console web. Il utilise son cookie HttpOnly et ne réutilise jamais le jeton appareil. */
export interface SessionConsole {
  readonly base: string;
  readonly utilisateur: string;
  readonly roles: readonly string[];
  readonly csrf: string;
}

export interface SpecificationAgent {
  readonly id: string;
  readonly departement: string;
  readonly responsabilite: string;
  readonly palier_modele: string;
  readonly outils: readonly string[];
  readonly budget_jour: number;
  readonly budget_mois: number;
  readonly limite_tours: number;
  readonly limite_reessais: number;
  readonly limite_concurrence: number;
  readonly declencheurs: readonly Readonly<Record<string, string>>[];
}

export interface ProfilAgent extends SpecificationAgent {
  readonly actif: boolean;
  readonly supprime: boolean;
  readonly revision: number;
  readonly cree_le: string;
  readonly modifie_le: string;
  readonly modifie_par: string;
}

type Fetcher = typeof fetch;
type Reponse = { readonly ok: boolean; readonly status: number; json(): Promise<unknown> };

function normaliserBase(url: string): string {
  const base = url.trim().replace(/\/+$/, "");
  if (!base) throw new Error("URL de console absente");
  let parsed: URL;
  try { parsed = new URL(base); } catch { throw new Error("URL de console invalide"); }
  if (parsed.protocol !== "https:" && parsed.hostname !== "localhost" && parsed.hostname !== "127.0.0.1") {
    throw new Error("La console doit utiliser HTTPS");
  }
  return base;
}

async function jsonRequis(reponse: Reponse): Promise<Record<string, unknown>> {
  if (!reponse.ok) throw new Error(`Console indisponible (${reponse.status})`);
  const corps: unknown = await reponse.json();
  if (corps === null || typeof corps !== "object" || Array.isArray(corps)) throw new Error("Réponse console invalide");
  return corps as Record<string, unknown>;
}

/** Le mot de passe ne quitte cette fonction que dans le POST; seul le jeton CSRF revient en mémoire. */
export async function creerSessionConsole(
  url: string, identifiant: string, motDePasse: string, fetcher: Fetcher = fetch, personneAppareil = identifiant,
): Promise<SessionConsole> {
  const base = normaliserBase(url);
  const formulaire = new URLSearchParams({ identifiant, mot_de_passe: motDePasse });
  const connexion = await fetcher(`${base}/connexion`, {
    method: "POST", credentials: "include",
    headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: formulaire.toString(),
  });
  if (!connexion.ok) throw new Error(`Connexion refusée (${connexion.status})`);
  const corps = await jsonRequis(await fetcher(`${base}/api/session`, { method: "GET", credentials: "include" }));
  const utilisateur = corps.utilisateur;
  const roles = corps.roles;
  const csrf = corps.csrf;
  if (typeof utilisateur !== "string" || !Array.isArray(roles) || !roles.every((r) => typeof r === "string") || typeof csrf !== "string") {
    throw new Error("Session console invalide");
  }
  if (utilisateur !== personneAppareil) throw new Error("L’identité de la console ne correspond pas à la personne de l’appareil");
  if (!roles.some((role) => role === "admin" || role === "nathan_owner")) throw new Error("Cette session console n’a pas le rôle admin");
  return { base, utilisateur, roles, csrf };
}

export class ClientConsoleAgents {
  constructor(
    private readonly session: SessionConsole, private readonly fetcher: Fetcher = fetch,
    private readonly personneActuelle: () => string | null = () => session.utilisateur,
  ) {}

  private async requete(url: string, init: RequestInit = {}): Promise<Record<string, unknown>> {
    if (this.personneActuelle() !== this.session.utilisateur) throw new Error("Identité appareil modifiée : reconnectez la console");
    const reponse = await this.fetcher(`${this.session.base}${url}`, {
      ...init, credentials: "include",
      headers: { ...(init.headers ?? {}), ...(init.method && init.method !== "GET" ? { "X-CSRF-Token": this.session.csrf } : {}) },
    });
    if (this.personneActuelle() !== this.session.utilisateur) throw new Error("Identité appareil modifiée : reconnectez la console");
    const corps = await jsonRequis(reponse);
    if (this.personneActuelle() !== this.session.utilisateur) throw new Error("Identité appareil modifiée : reconnectez la console");
    return corps;
  }

  async lister(): Promise<ProfilAgent[]> {
    const corps = await this.requete("/api/agents");
    if (!Array.isArray(corps.agents)) throw new Error("Liste d’agents invalide");
    return corps.agents as ProfilAgent[];
  }

  async obtenir(id: string): Promise<ProfilAgent> {
    const corps = await this.requete(`/api/agents/${encodeURIComponent(id)}`);
    if (!corps.agent || typeof corps.agent !== "object") throw new Error("Profil agent invalide");
    return corps.agent as ProfilAgent;
  }

  async historique(id: string): Promise<ProfilAgent[]> {
    const corps = await this.requete(`/api/agents/${encodeURIComponent(id)}/historique`);
    if (!Array.isArray(corps.historique)) throw new Error("Historique agent invalide");
    return corps.historique as ProfilAgent[];
  }

  async creer(spec: SpecificationAgent, mutation_id: string): Promise<ProfilAgent> {
    return this.profil(await this.requete("/api/agents", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ spec, mutation_id }) }));
  }

  async modifier(id: string, spec: SpecificationAgent, mutation_id: string, revision_attendue: number): Promise<ProfilAgent> {
    return this.profil(await this.requete(`/api/agents/${encodeURIComponent(id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ spec, mutation_id, revision_attendue }) }));
  }

  async activer(id: string, actif: boolean, mutation_id: string, revision_attendue: number): Promise<ProfilAgent> {
    return this.profil(await this.requete(`/api/agents/${encodeURIComponent(id)}/activation`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actif, mutation_id, revision_attendue }) }));
  }

  async supprimer(id: string, mutation_id: string, revision_attendue: number): Promise<ProfilAgent> {
    return this.profil(await this.requete(`/api/agents/${encodeURIComponent(id)}`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mutation_id, revision_attendue }) }));
  }

  async deconnecter(): Promise<void> {
    if (this.personneActuelle() !== this.session.utilisateur) throw new Error("Identité appareil modifiée : session console invalidée");
    const body = new URLSearchParams({ csrf: this.session.csrf });
    const reponse = await this.fetcher(`${this.session.base}/deconnexion`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: body.toString(),
    });
    if (!reponse.ok) throw new Error(`Déconnexion refusée (${reponse.status})`);
  }

  private profil(corps: Record<string, unknown>): ProfilAgent {
    if (!corps.agent || typeof corps.agent !== "object") throw new Error("Profil agent invalide");
    return corps.agent as ProfilAgent;
  }
}
