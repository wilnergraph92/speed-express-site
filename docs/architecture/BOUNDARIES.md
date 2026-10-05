# Frontières entre domaines (contextes)

Chaque domaine **possède** ses tables : lui seul y écrit. Les autres l'appellent par une
fonction de la façade ou réagissent à ses événements. **Jamais d'écriture croisée.**

| Domaine | Possède | Expose (fonctions / événements) | Dépend de |
|---|---|---|---|
| **Identité et accès** | `organization`, `branch`, `app_user`, droits | « qui est connecté, que peut-il faire » | Supabase Auth |
| **Client** | `customer`, `device` (clients) | créer/lire client ; adresses | Identité |
| **Cycle de vie du colis** | `parcel`, `parcel_status`, `parcel_transition`, `tracking_event` | `lg_transition_parcel` ; tous les `Parcel*` | Client, Entrepôt |
| **Entrepôt** | `warehouse`, `warehouse_location`, `scan`, mouvements | réception, vérification, rangement | Colis |
| **Transport** | `consolidation`, `shipment`, `shipment_item`, `transport`, `customs_*` | fermer consolidation, créer/expédier/arriver | Colis, Entrepôt |
| **Dernier kilomètre** | `delivery`, `route`, `trip`, `stop`, `driver`, `pickup`, `proof_of_delivery`, `incident` | assigner, accepter, livrer | Colis, Transport |
| **Finance** | `quote`, `rate_card`, `invoice`, `invoice_item`, `payment`, … | devis, facture, paiement | Colis, Client |
| **Notification** | `notification`, `device` (push) | envoi | tous, par événements |
| **Audit** | `audit_log`, `domain_event` | lecture seule | tous, par déclencheurs |

Règles :
1. **Sens des dépendances** : Finance, Notification et Audit **réagissent** ; ils ne pilotent jamais le colis.
2. **Colis ≠ Expédition** : leurs statuts sont séparés (ADR 0006) ; l'expédition ne modifie pas un statut de colis directement, elle **émet un événement** que le cycle de vie du colis traduit en transition.
3. **Une écriture, un événement, une trace d'audit**, dans la même transaction.
4. L'ancien schéma `public` (`clients`, `colis`, `factures`…) reste la source de vérité **tant que la bascule n'est pas décidée** (`MIGRATION-STRATEGY.md`).
