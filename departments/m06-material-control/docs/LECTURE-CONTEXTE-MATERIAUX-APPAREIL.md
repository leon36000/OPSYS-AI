# Contexte et prévu des matériaux du WCT choisi

`m6_lire_contexte_materiaux_appareil` est une lecture DEVICE T0/N0 pour employee et admin. Ses quatre arguments obligatoires sont `intervention_id`, `wct_id`, `decalage` et `limite`, sans propriété supplémentaire. Les IDs restent verbatim : non vides selon Python `strip`, sans caractères Unicode Cc/Cs, au plus256 codepoints. Décalage entier strict0..10000, limite1..8 ; booléens refusés.

La personne active et son rôle actuel sont revérifiés avant toute source. L'admission individuelle M4 lit séparément son registre d'autorisation ; pour employee, le dernier assignement ou la dernière transition en route doit désigner la personne authentifiée. Ce contrôle précède la lecture du bus WCT, du prévu M6 et des publications M3. Aucun profil d'équipe/configuration n'est requis pour ce WCT complété individuellement. L'admission M4 ne constitue donc pas « zéro lecture de registre » ; elle reste distincte des sources métier protégées.

Le registre M4 doit garder sa chaîne et ses invariants d'outbox valides. Le WCT réellement publié par m04-field-ops est contrôlé au catalogue et doit égaler la charge de complétion M4, y compris son hash natif, son intervention et son technicien. L'appareil ne fournit aucune identité, devis, chantier, quantité, configuration ou origine d'agent.

Le prévu est celui de `besoins_prevus.pour_devis` : premier définitif, sinon dernier provisoire reçu. Le chantier suit exclusivement `acces.chantier_attendu` : chantier non nul du prévu ; à défaut intervention pour employee, null pour admin. Un prévu vide connu demeure distinct d'un prévu absent. Aucun rang provisoire écarté n'enrichit un définitif.

La réponse DIRECTE est `{ok:true,resultat:DTO}`. Le DTO fermé contient :

- `wct` : wct_id, intervention_id, devis_id nullable, horodatage_completion, hash_maillon, reference_bus `{type:"m4.travaux_termines",evenement_id:wct_id}` ;
- `chantier` : chantier_id nullable, origine parmi prevu_m6/intervention_employee/absent_admin ;
- `prevu` : statut absent/definitif/provisoire_estimation_m3 et source nullable. Source : registre besoins_prevus, rang durable0-based, empreinte_snapshot SHA256 du maillon copié (pas hash de chaîne), estimation_id/rang_m3/bareme_version null pour définitif, horodatage nullable et reference_m3 nullable `{type,evenement_id}` ;
- `lignes` : position_source, materiau_id, unite, quantite_estimee texte positif ASCII sans exposant et origine_quantite texte_m3_verifie/nombre_m6_persiste ;
- `pagination` : decalage, limite, affichees, total, suivant nullable, reste, courante true ;
- `manques`, `couverture`, borne_caracteres5400 et taille_caracteres du DIRECT entier.

`couverture` vaut exactement `{objet:"contexte_et_prevu_du_wct",quantite_reelle:"non_renseignee",pages:"courantes",plafond_lignes:10000}`. Les positions de la page sont decalage+i dans l'ordre source. Le décalage au-delà du total donne une page vide. Une source nouvelle remplace la page courante ; aucun snapshot ou cache mobile n'est créé.

Les manques ordonnés sont devis_absent iff devis null, prevu_absent iff source null, chantier_source_absent iff chantier null ; pour un prévu présent seulement, horodatage_prevu_absent iff sa date null et provenance_m3_absente iff référence M3 null. Une référence m3.devis_accepte impose sa date d'acceptation réelle valide ; m3.besoins_materiaux et référence absente impliquent une date null. Le prévu M6 n'a pas de date native. La date de complétion n'est jamais empruntée comme date du prévu.

Le provisoire est validé par reconstruction de son contrat M3→M6 conservé, puis par le validateur existant : confiance, détails, facteurs absents, identités et quantités doivent concorder, même si la publication M3 manque. La provenance publiée exige le producteur m03-estimation, le catalogue valide et une concordance avec le prévu sélectionné. Le texte M3 n'est repris que si l'identité, l'unité et la quantité concordent exactement avec le nombre M6 persisté ; sinon ce nombre fini est représenté en texte décimal et marqué nombre_m6_persiste. Zéros initiaux et finaux du texte M3 vérifié sont conservés. Aucune quantité réelle, conversion d'unité ou majoration par facteur-perte n'est calculée.

Les copies des lignes de registre/publications nécessaires sont limitées à10000 après copie ; les lignes du prévu choisi également. Ce plafond ne garantit pas l'allocation initiale. Le DIRECT entier est mesuré par point fixe sous5400 caractères : une page peut contenir moins que limite ; un premier élément trop grand donne un refus nommé sans tronquer. Cap contrôle aussi sa limite configurée avant tout fallback d'artefact.

Les refus métier DIRECTS ont `resultat:{accepte:false,verdict:{code,detail}}`, préfixe REJ-M6-CONTEXTE- et suffixes ARGUMENTS-INVALIDES, IDENTITE-INVALIDE, INTERVENTION-NON-ASSIGNEE, WCT-INCONNU, LIAISON-INCOHERENTE, SOURCE-INVALIDE, BORNE-SOURCES, SORTIE-TROP-VOLUMINEUSE. Les détails sont fixes, sans message brut d'exception ou source corrompue. Le schéma peut refuser des arguments avant la fonction (`ok:false,erreur:"arguments_invalides"`).

Aucun coût, prix, marge, contact, technicien, GPS, preuve photo, facteur-perte ni payload brut n'est projeté. La lecture n'écrit aucun registre, stock, artefact, fichier ou formulaire. Les tests utilisent une vraie complétion M4, des octets CAS explicitement fictifs, le vrai récepteur M6 des publications M3 fictives et SQLite/executer_atomique. Ils comparent les49 tables intégrales avant/après et relisent après libération de la connexion. Cette preuve Python/SQL ne qualifie pas Gateway DEVICE opaque, HTTP, téléphone, Expo SQLite ou Hermes.

Le formulaire peut explicitement copier les lignes estimées, mais la quantité réelle reste vide. Une relecture réseau ne remplace jamais une ligne déjà saisie ; réseau indisponible ou contexte non autorisé=>inconnu, brouillon conservé. Les preuves photos pertes/bris demeurent une tranche ultérieure.
