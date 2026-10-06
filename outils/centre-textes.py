#!/usr/bin/env python3
"""Les textes du centre de commande : UNE table (français, anglais, espagnol, créole), deux sorties.

    python3 outils/centre-textes.py

Elle écrit, entre des repères, (1) les <span data-t="…"> du gabarit de la page (outils/espace/tableau-de-bord.html) et (2) les entrées du
dictionnaire (assets/js/lang-dict-11.js, celui que le tableau de bord charge). Relancée, elle ne change rien si la table n'a pas changé.
Ajouter un texte au centre de commande, c'est ajouter UNE ligne ici, puis relancer ce script et `python3 outils/mise-en-page.py`.

Mêmes garde-fous que outils/portail-textes.py : deux clés avec le même français mais des traductions différentes, un texte vide, une
apostrophe typographique (le moteur de traduction ne la reconnaît pas), des accolades qui ne se retrouvent pas d'une langue à l'autre.
Une entrée qui existe déjà dans le dictionnaire avec une AUTRE traduction est laissée telle quelle : celle du dictionnaire fait foi.

Les familles (statuts, types, rôles…) sont générées à partir des valeurs que la base connaît (outils/tests/centre-enums.json) : si la base
en gagne une, outils/tests/centre-textes.cjs échoue tant qu'elle n'est pas nommée ici.
"""
import json
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
GABARIT = SITE / 'outils/espace/tableau-de-bord.html'
DICO = SITE / 'assets/js/lang-dict-11.js'
DICO_COMMUN = SITE / 'assets/js/lang-dict.js'
D1, F1 = '<!-- centre:debut -->', '<!-- centre:fin -->'
D2, F2 = '  // --- centre:debut ---', '  // --- centre:fin ---'

# (clé, français, anglais, espagnol, créole)
T = []


def a(*lignes):
    T.extend(lignes)


def famille(prefixe, valeurs):
    """valeurs : {code: (fr, en, es, ht)} → une clé « prefixe + code » par code."""
    for code, (fr, en, es, ht) in valeurs.items():
        T.append((prefixe + code, fr, en, es, ht))


# ---- l'onglet, la navigation, les états ---------------------------------------------------------------------------------------------
a(('c-tab', 'Centre de commande', 'Command center', 'Centro de mando', 'Sant kòmandman'),
  ('c-nav-titre', 'Sections du centre de commande', 'Command center sections', 'Secciones del centro de mando', 'Seksyon sant kòmandman an'),
  ('c-grp-pilotage', 'Pilotage', 'Overview', 'Panorama', 'Apèsi jeneral'),
  ('c-grp-operations', 'Opérations', 'Operations', 'Operaciones', 'Operasyon'),
  ('c-grp-clients', 'Clients et finances', 'Customers and finance', 'Clientes y finanzas', 'Kliyan ak finans'),
  ('c-grp-direction', 'Direction', 'Management', 'Dirección', 'Direksyon'),
  ('c-chargement', 'Chargement…', 'Loading…', 'Cargando…', 'Chajman…'),
  ('c-reessayer', 'Réessayer', 'Try again', 'Reintentar', 'Eseye ankò'),
  ('c-actualiser', 'Actualiser', 'Refresh', 'Actualizar', 'Aktyalize'),
  ('c-auto', 'Actualisation automatique (chaque minute)', 'Automatic refresh (every minute)', 'Actualización automática (cada minuto)', 'Aktyalizasyon otomatik (chak minit)'),
  ('c-maj', 'Mis à jour à {heure}', 'Updated at {heure}', 'Actualizado a las {heure}', 'Mizajou a {heure}'),
  ('c-vide', 'Rien à afficher avec ces filtres.', 'Nothing to show with these filters.', 'Nada que mostrar con estos filtros.', 'Pa gen anyen pou montre ak filt sa yo.'),
  ('c-tableau', 'Tableau des résultats', 'Results table', 'Tabla de resultados', 'Tablo rezilta yo'),
  ('c-pagination', 'Pages de résultats', 'Result pages', 'Páginas de resultados', 'Paj rezilta yo'),
  ('c-page-info', '{debut}–{fin} sur {total}', '{debut}–{fin} of {total}', '{debut}–{fin} de {total}', '{debut}–{fin} sou {total}'),
  ('c-precedent', 'Précédent', 'Previous', 'Anterior', 'Anvan'),
  ('c-suivant', 'Suivant', 'Next', 'Siguiente', 'Apre'),
  ('c-par-statut', 'Résultats par statut', 'Results by status', 'Resultados por estado', 'Rezilta pa eta'),
  ('c-voir-tout', 'Voir tout', 'See all', 'Ver todo', 'Wè tout'),
  ('c-envoi', 'Envoi en cours…', 'Sending…', 'Enviando…', 'Y ap voye…'),
  ('c-envoyer', 'Envoyer', 'Send', 'Enviar', 'Voye'),
  ('c-aucune', 'Aucune', 'None', 'Ninguna', 'Okenn'),
  ('c-non-autorise', 'Non autorisé', 'Not allowed', 'No autorizado', 'Pa otorize'),
  ('c-age-min', 'il y a {nombre} min', '{nombre} min ago', 'hace {nombre} min', 'gen {nombre} min'),
  ('c-age-h', 'il y a {nombre} h', '{nombre} h ago', 'hace {nombre} h', 'gen {nombre} è'),
  ('c-age-j', 'il y a {nombre} j', '{nombre} d ago', 'hace {nombre} d', 'gen {nombre} jou'),
  ('c-il-y-a-min', 'il y a {nombre} min', '{nombre} min ago', 'hace {nombre} min', 'gen {nombre} min'),
  ('c-jours', '{nombre} jour(s)', '{nombre} day(s)', '{nombre} día(s)', '{nombre} jou'),
  ('c-retard', 'En retard', 'Late', 'Con retraso', 'An reta'),
  ('c-actif', 'Actif', 'Active', 'Activo', 'Aktif'),
  ('c-inactif', 'Inactif', 'Inactive', 'Inactivo', 'Pa aktif'),
  ('c-disponible', 'Disponible', 'Available', 'Disponible', 'Disponib'),
  ('c-indisponible', 'Indisponible', 'Unavailable', 'No disponible', 'Pa disponib'))

# ---- les sections ---------------------------------------------------------------------------------------------------------------------
famille('c-sec-', {
    'commande': ('Centre de commande', 'Command center', 'Centro de mando', 'Sant kòmandman'), 'rapports': ('Rapports', 'Reports', 'Informes', 'Rapò'), 'flux': ('Flux', 'Flow', 'Flujo', 'Koule'),
    'colis': ('Colis', 'Parcels', 'Paquetes', 'Kolis'), 'expeditions': ('Expéditions', 'Shipments', 'Envíos', 'Ekspedisyon'), 'entrepot': ('Entrepôt', 'Warehouse', 'Almacén', 'Depo'),
    'consolidations': ('Consolidations', 'Consolidations', 'Consolidaciones', 'Gwoupman kolis'), 'transport': ('Transport', 'Transport', 'Transporte', 'Transpò'),
    'poste': ('Poste de scan', 'Scan station', 'Puesto de escaneo', 'Pòs eskanè'), 'analytique': ('Analytique', 'Analytics', 'Analítica', 'Analitik'),
    'sante': ('Santé du système', 'System health', 'Salud del sistema', 'Sante sistèm nan'),
    'chauffeurs': ('Chauffeurs', 'Drivers', 'Conductores', 'Chofè'), 'enlevements': ('Enlèvements', 'Pickups', 'Recogidas', 'Ranmasaj'), 'livraisons': ('Livraisons', 'Deliveries', 'Entregas', 'Livrezon'),
    'douane': ('Douane', 'Customs', 'Aduana', 'Dwàn'), 'incidents': ('Incidents', 'Issues', 'Incidencias', 'Pwoblèm'), 'notifications': ('Notifications', 'Notifications', 'Notificaciones', 'Notifikasyon'),
    'clients': ('Clients', 'Customers', 'Clientes', 'Kliyan'), 'support': ('Support', 'Support', 'Soporte', 'Sipò'), 'facturation': ('Facturation', 'Billing', 'Facturación', 'Faktirasyon'),
    'paiements': ('Paiements', 'Payments', 'Pagos', 'Peman'), 'utilisateurs': ('Utilisateurs', 'Users', 'Usuarios', 'Itilizatè'), 'audit': ("Journal d'audit", 'Audit log', 'Registro de auditoría', 'Jounal odit'),
    'parametres': ('Réglages', 'Settings', 'Ajustes', 'Paramèt')})

# ---- les filtres ----------------------------------------------------------------------------------------------------------------------
a(('c-filtres-titre', 'Filtres', 'Filters', 'Filtros', 'Filt'),
  ('c-f-tous', 'Tous', 'All', 'Todos', 'Tout'),
  ('c-filtres-actifs', '{nombre} actif(s)', '{nombre} active', '{nombre} activo(s)', '{nombre} aktif'),
  ('c-f-statut', 'Statut', 'Status', 'Estado', 'Eta'),
  ('c-f-pays', 'Pays', 'Country', 'País', 'Peyi'),
  ('c-f-service', 'Service', 'Service', 'Servicio', 'Sèvis'),
  ('c-f-ville', 'Ville', 'City', 'Ciudad', 'Vil'),
  ('c-f-entrepot', 'Entrepôt', 'Warehouse', 'Almacén', 'Depo'),
  ('c-f-client', 'Client', 'Customer', 'Cliente', 'Kliyan'),
  ('c-f-client-aide', 'Code, e-mail ou nom', 'Code, e-mail or name', 'Código, correo o nombre', 'Kòd, imèl oswa non'),
  ('c-f-du', 'Du', 'From', 'Desde', 'Soti'),
  ('c-f-au', 'Au', 'To', 'Hasta', 'Jiska'),
  ('c-appliquer', 'Appliquer', 'Apply', 'Aplicar', 'Aplike'),
  ('c-raz', 'Réinitialiser', 'Reset', 'Restablecer', 'Reyinisyalize'))
famille('c-svc-', {'air': ('Aérien', 'Air', 'Aéreo', 'Avyon'), 'sea': ('Maritime', 'Sea', 'Marítimo', 'Bato'), 'ground': ('Terrestre', 'Land', 'Terrestre', 'Kamyon')})

# ---- l'accueil : chiffres du jour, file de travail ---------------------------------------------------------------------------------------
a(('c-note-periode', 'Les chiffres « du jour » ne suivent pas la période choisie : seul le revenu de la période en tient compte.', 'The “today” figures do not follow the chosen period: only the period revenue does.', 'Las cifras «de hoy» no siguen el período elegido: solo los ingresos del período lo hacen.', 'Chif « jodi a » yo pa swiv peryòd ou chwazi a : se sèlman revni peryòd la ki swiv li.'),
  ('c-kpi-grp-colis', 'Colis', 'Parcels', 'Paquetes', 'Kolis'),
  ('c-kpi-grp-expeditions', 'Expéditions', 'Shipments', 'Envíos', 'Ekspedisyon'),
  ('c-kpi-grp-livraisons', 'Livraisons', 'Deliveries', 'Entregas', 'Livrezon'),
  ('c-kpi-grp-alertes', 'À surveiller', 'To watch', 'A vigilar', 'Pou siveye'),
  ('c-kpi-grp-support', 'Support', 'Support', 'Soporte', 'Sipò'),
  ('c-kpi-grp-argent', 'Argent', 'Money', 'Dinero', 'Lajan'),
  ('c-kpi-parcels_received_today', "Colis reçus aujourd'hui", 'Parcels received today', 'Paquetes recibidos hoy', 'Kolis resevwa jodi a'),
  ('c-kpi-parcels_in_warehouse', 'Colis en entrepôt', 'Parcels in the warehouse', 'Paquetes en el almacén', 'Kolis nan depo a'),
  ('c-kpi-parcels_at_hub', 'Colis au hub', 'Parcels at the hub', 'Paquetes en el hub', 'Kolis nan hub la'),
  ('c-kpi-parcels_on_hold', 'Colis retenus', 'Parcels on hold', 'Paquetes retenidos', 'Kolis kenbe'),
  ('c-kpi-consolidations_open', 'Consolidations ouvertes', 'Open consolidations', 'Consolidaciones abiertas', 'Gwoupman kolis ouvè'),
  ('c-kpi-shipments_ready', 'Expéditions prêtes', 'Shipments ready', 'Envíos listos', 'Ekspedisyon pare'),
  ('c-kpi-shipments_in_transit', 'Expéditions en transit', 'Shipments in transit', 'Envíos en tránsito', 'Ekspedisyon an tranzit'),
  ('c-kpi-shipments_customs', 'Expéditions en douane', 'Shipments in customs', 'Envíos en aduana', 'Ekspedisyon nan dwàn'),
  ('c-kpi-deliveries_today', "Livraisons d'aujourd'hui", "Today's deliveries", 'Entregas de hoy', 'Livrezon jodi a'),
  ('c-kpi-deliveries_in_progress', 'Livraisons en cours', 'Deliveries in progress', 'Entregas en curso', 'Livrezon k ap fèt'),
  ('c-kpi-deliveries_delayed', 'Livraisons en retard', 'Late deliveries', 'Entregas con retraso', 'Livrezon an reta'),
  ('c-kpi-incidents_open', 'Incidents ouverts', 'Open issues', 'Incidencias abiertas', 'Pwoblèm ouvè'),
  ('c-kpi-incidents_high', 'Incidents graves', 'Serious issues', 'Incidencias graves', 'Pwoblèm grav'),
  ('c-kpi-pickup_requests_pending', "Demandes d'enlèvement à traiter", 'Pickup requests to process', 'Solicitudes de recogida por tramitar', 'Demann ranmasaj pou trete'),
  ('c-kpi-delivery_requests_pending', 'Demandes de livraison à traiter', 'Delivery requests to process', 'Solicitudes de entrega por tramitar', 'Demann livrezon pou trete'),
  ('c-kpi-tickets_open', 'Tickets ouverts', 'Open tickets', 'Tickets abiertos', 'Tikè ouvè'),
  ('c-kpi-tickets_waiting_staff', "Tickets en attente de l'équipe", 'Tickets waiting for the team', 'Tickets a la espera del equipo', 'Tikè k ap tann ekip la'),
  ('c-kpi-revenue_today_usd', "Revenu du jour", "Today's revenue", 'Ingresos del día', 'Revni jodi a'),
  ('c-kpi-revenue_month_usd', 'Revenu du mois', "This month's revenue", 'Ingresos del mes', 'Revni mwa a'),
  ('c-kpi-revenue_period_usd', 'Revenu de la période', 'Revenue for the period', 'Ingresos del período', 'Revni peryòd la'),
  ('c-kpi-unpaid', 'Impayés ({devise})', 'Unpaid ({devise})', 'Impagos ({devise})', 'Enpeye ({devise})'),
  ('c-kpi-unpaid-detail', '{factures} facture(s), {clients} client(s)', '{factures} invoice(s), {clients} customer(s)', '{factures} factura(s), {clients} cliente(s)', '{factures} fakti, {clients} kliyan'),
  ('c-kpi-overdue_invoices', 'Factures en retard de paiement', 'Overdue invoices', 'Facturas vencidas', 'Fakti an reta'),
  ('c-date-comptable', 'écritures du {date}', 'entries of {date}', 'asientos del {date}', 'ekriti {date}'),
  ('c-att-titre', 'À traiter', 'To do', 'Por hacer', 'Pou fè'),
  ('c-att-rien', "Rien n'attend l'équipe pour le moment.", 'Nothing is waiting for the team right now.', 'Nada espera al equipo por ahora.', 'Pa gen anyen k ap tann ekip la pou kounye a.'),
  ('c-att-depuis', 'le plus ancien : {age}', 'oldest: {age}', 'el más antiguo: {age}', 'pi ansyen an : {age}'),
  ('c-flux-titre', 'Flux : expédition → transport → hub → livraison → chauffeur', 'Flow: shipment → transport → hub → delivery → driver', 'Flujo: envío → transporte → hub → entrega → conductor', 'Koule : ekspedisyon → transpò → hub → livrezon → chofè'),
  ('c-flux-vide', 'Aucune expédition active.', 'No active shipment.', 'Ningún envío activo.', 'Pa gen okenn ekspedisyon aktif.'),
  ('c-flux-intro', "Chaque ligne suit une expédition de bout en bout : son transport, le hub d'arrivée, ses colis et les livraisons qui en partent.", 'Each row follows a shipment from end to end: its transport, the arrival hub, its parcels and the deliveries leaving from it.', 'Cada fila sigue un envío de principio a fin: su transporte, el hub de llegada, sus paquetes y las entregas que salen de él.', 'Chak ranje swiv yon ekspedisyon soti nan kòmansman rive nan fen : transpò li, hub li rive a, kolis li yo ak livrezon ki soti ladan l.'))
famille('c-att-', {
    'pickup_requests': ("Demandes d'enlèvement", 'Pickup requests', 'Solicitudes de recogida', 'Demann ranmasaj'), 'delivery_requests': ('Demandes de livraison', 'Delivery requests', 'Solicitudes de entrega', 'Demann livrezon'),
    'deliveries_delayed': ('Livraisons en retard', 'Late deliveries', 'Entregas con retraso', 'Livrezon an reta'), 'incidents_high': ('Incidents graves ouverts', 'Open serious issues', 'Incidencias graves abiertas', 'Pwoblèm grav ouvè'),
    'parcels_on_hold': ('Colis retenus', 'Parcels on hold', 'Paquetes retenidos', 'Kolis kenbe'), 'shipments_late': ('Expéditions en retard sur leur arrivée prévue', 'Shipments behind their planned arrival', 'Envíos con retraso sobre su llegada prevista', 'Ekspedisyon an reta sou rive yo prevwa a'),
    'tickets_waiting': ("Tickets qui attendent l'équipe", 'Tickets waiting for the team', 'Tickets que esperan al equipo', 'Tikè k ap tann ekip la'), 'invoices_overdue': ('Factures en retard de paiement', 'Overdue invoices', 'Facturas vencidas', 'Fakti an reta')})

# ---- les colonnes ---------------------------------------------------------------------------------------------------------------------
COLONNES = {
    'acteur': ('Acteur', 'Actor', 'Actor', 'Akè'), 'actif': ('Actif', 'Active', 'Activo', 'Aktif'), 'action': ('Action', 'Action', 'Acción', 'Aksyon'), 'actions': ('Actions', 'Actions', 'Acciones', 'Aksyon'),
    'adresse': ('Adresse', 'Address', 'Dirección', 'Adrès'), 'arrivee': ('Arrivée', 'Arrival', 'Llegada', 'Rive'), 'attente': ('Attente', 'Waiting', 'Espera', 'Datant'), 'but': ('But', 'Purpose', 'Finalidad', 'Objektif'),
    'canal': ('Canal', 'Channel', 'Canal', 'Kanal'), 'changement': ('Changement', 'Change', 'Cambio', 'Chanjman'), 'chauffeur': ('Chauffeur', 'Driver', 'Conductor', 'Chofè'), 'client': ('Client', 'Customer', 'Cliente', 'Kliyan'),
    'code': ('Code', 'Code', 'Código', 'Kòd'), 'colis': ('Colis', 'Parcels', 'Paquetes', 'Kolis'), 'colis-attendus': ('Colis attendus', 'Expected parcels', 'Paquetes esperados', 'Kolis yo atann'),
    'consolidation': ('Consolidation', 'Consolidation', 'Consolidación', 'Gwoupman kolis'), 'contact': ('Contact', 'Contact', 'Contacto', 'Kontak'), 'correlation': ('Corrélation', 'Correlation', 'Correlación', 'Korelasyon'),
    'courtier': ('Courtier', 'Broker', 'Agente', 'Koutye'), 'cree': ('Créé le', 'Created', 'Creado', 'Kreye'), 'date': ('Date', 'Date', 'Fecha', 'Dat'), 'depart': ('Départ', 'Departure', 'Salida', 'Depa'),
    'deposee': ('Déposée', 'Submitted', 'Presentada', 'Depoze'), 'dernier-colis': ('Dernier colis', 'Last parcel', 'Último paquete', 'Dènye kolis'), 'dernier-message': ('Dernier message', 'Last message', 'Último mensaje', 'Dènye mesaj'),
    'derniere-connexion': ('Dernière connexion', 'Last sign-in', 'Última conexión', 'Dènye koneksyon'), 'description': ('Description', 'Description', 'Descripción', 'Deskripsyon'), 'destination': ('Destination', 'Destination', 'Destino', 'Destinasyon'),
    'detail': ('Détail', 'Detail', 'Detalle', 'Detay'), 'droits': ('Droits', 'Permissions', 'Permisos', 'Dwa'), 'email': ('E-mail', 'E-mail', 'Correo electrónico', 'Imèl'), 'emise': ('Émise', 'Issued', 'Emitida', 'Emèt'),
    'entrepot': ('Entrepôt', 'Warehouse', 'Almacén', 'Depo'), 'envoyee': ('Envoyée', 'Sent', 'Enviada', 'Voye'), 'etape': ('Étape', 'Step', 'Etapa', 'Etap'), 'expedition': ('Expédition', 'Shipment', 'Envío', 'Ekspedisyon'),
    'expeditions': ('Expéditions', 'Shipments', 'Envíos', 'Ekspedisyon'), 'facture': ('Facture', 'Invoice', 'Factura', 'Fakti'), 'fermee': ('Fermée', 'Closed', 'Cerrada', 'Fèmen'), 'genre': ('Genre', 'Kind', 'Tipo', 'Kalite'),
    'gravite': ('Gravité', 'Severity', 'Gravedad', 'Gravite'), 'hub': ('Hub', 'Hub', 'Hub', 'Hub'), 'impayes': ('Impayés', 'Unpaid', 'Impagos', 'Enpeye'), 'lieu': ('Lieu', 'Place', 'Lugar', 'Kote'),
    'livraisons': ('Livraisons', 'Deliveries', 'Entregas', 'Livrezon'), 'maj': ('Mis à jour', 'Updated', 'Actualizado', 'Mizajou'), 'messages': ('Messages', 'Messages', 'Mensajes', 'Mesaj'),
    'missions-jour': ("Missions du jour", "Today's tasks", 'Misiones del día', 'Misyon jodi a'), 'modele': ('Modèle', 'Template', 'Plantilla', 'Modèl'), 'montant': ('Montant', 'Amount', 'Importe', 'Montan'), 'nom': ('Nom', 'Name', 'Nombre', 'Non'),
    'numero': ('Numéro', 'Number', 'Número', 'Nimewo'), 'objet': ('Objet', 'Object', 'Objeto', 'Objè'), 'ou': ('Où', 'Where', 'Dónde', 'Ki kote'), 'ouverte': ('Ouverte', 'Open', 'Abierta', 'Ouvè'),
    'ouvertes': ('Ouvertes', 'Open', 'Abiertas', 'Ouvè'), 'paye': ('Payé', 'Paid', 'Pagado', 'Peye'), 'poids': ('Poids', 'Weight', 'Peso', 'Pwa'), 'position': ('Position', 'Position', 'Posición', 'Pozisyon'),
    'reference': ('Référence', 'Reference', 'Referencia', 'Referans'), 'resultat': ('Résultat', 'Result', 'Resultado', 'Rezilta'), 'role': ('Rôle', 'Role', 'Rol', 'Wòl'), 'service': ('Service', 'Service', 'Servicio', 'Sèvis'),
    'solde': ('Solde', 'Balance', 'Saldo', 'Balans'), 'statut': ('Statut', 'Status', 'Estado', 'Eta'), 'succursale': ('Succursale', 'Branch', 'Sucursal', 'Branch'), 'sujet': ('Sujet', 'Subject', 'Asunto', 'Sijè'),
    'tickets': ('Tickets', 'Tickets', 'Tickets', 'Tikè'), 'total': ('Total', 'Total', 'Total', 'Total'), 'trajet': ('Trajet', 'Route', 'Trayecto', 'Wout'), 'transport': ('Transport', 'Transport', 'Transporte', 'Transpò'),
    'type': ('Type', 'Type', 'Tipo', 'Tip'), 'valeur': ('Valeur déclarée', 'Declared value', 'Valor declarado', 'Valè deklare'), 'vehicule': ('Véhicule', 'Vehicle', 'Vehículo', 'Machin'), 'zones': ('Zones', 'Zones', 'Zonas', 'Zòn')}
famille('c-col-', COLONNES)

# ---- les listes : phrases et mots -----------------------------------------------------------------------------------------------------
a(('c-interdit', 'Interdit', 'Prohibited', 'Prohibido', 'Entèdi'),
  ('c-pas-de-transport', 'Pas encore de transport', 'No transport yet', 'Aún sin transporte', 'Poko gen transpò'),
  ('c-arrive-le', 'arrivé le {date}', 'arrived {date}', 'llegado el {date}', 'rive {date}'),
  ('c-arrivee-prevue', 'arrivée prévue {date}', 'expected {date}', 'llegada prevista {date}', 'rive prevwa {date}'),
  ('c-prevu', 'Date prévue', 'Planned date', 'Fecha prevista', 'Dat prevwa'),
  ('c-prevu-le', 'prévu {date}', 'planned {date}', 'previsto {date}', 'prevwa {date}'),
  ('c-livraison-ligne', '{colis} colis le {date}', '{colis} parcel(s) on {date}', '{colis} paquete(s) el {date}', '{colis} kolis le {date}'),
  ('c-sans-chauffeur', 'Pas encore de chauffeur', 'No driver yet', 'Aún sin conductor', 'Poko gen chofè'),
  ('c-pas-expediee', 'Pas encore expédiée', 'Not shipped yet', 'Aún sin enviar', 'Poko ekspedye'),
  ('c-n-clients', '{nombre} client(s)', '{nombre} customer(s)', '{nombre} cliente(s)', '{nombre} kliyan'),
  ('c-n-ouverts', '{nombre} ouvert(s)', '{nombre} open', '{nombre} abierto(s)', '{nombre} ouvè'),
  ('c-faites-sur', '{faites} faite(s) sur {total}', '{faites} of {total} done', '{faites} de {total} hechas', '{faites} sou {total} fèt'),
  ('c-echouees', '{nombre} échouée(s)', '{nombre} failed', '{nombre} fallida(s)', '{nombre} echwe'),
  ('c-pas-de-position', 'Aucune position', 'No position', 'Sin posición', 'Pa gen pozisyon'),
  ('c-source-demande', 'Demande du client', 'Customer request', 'Solicitud del cliente', 'Demann kliyan an'),
  ('c-source-equipe', "Créé par l'équipe", 'Created by the team', 'Creado por el equipo', 'Ekip la kreye l'),
  ('c-source-mission', 'Mission', 'Task', 'Misión', 'Misyon'),
  ('c-enl-intro', "Les demandes des clients arrivent ici : approuvez-les (une mission d'enlèvement est alors créée) ou refusez-les avec un message que le client lira dans son espace.", 'Customer requests arrive here: approve them (a pickup task is then created) or refuse them with a message the customer will read in their area.', 'Las solicitudes de los clientes llegan aquí: apruébelas (se crea entonces una misión de recogida) o recházelas con un mensaje que el cliente leerá en su espacio.', 'Demann kliyan yo rive isit la : apwouve yo (lè sa a yo kreye yon misyon ranmasaj) oswa refize yo ak yon mesaj kliyan an pral li nan espas li.'),
  ('c-liv-intro', 'Les missions de livraison et les demandes des clients. Approuver une demande crée la livraison depuis le premier hub actif ; le colis passe par la machine des statuts.', 'Delivery tasks and customer requests. Approving a request creates the delivery from the first active hub; the parcel goes through the status machine.', 'Las misiones de entrega y las solicitudes de los clientes. Aprobar una solicitud crea la entrega desde el primer hub activo; el paquete pasa por la máquina de estados.', 'Misyon livrezon yo ak demann kliyan yo. Apwouve yon demann kreye livrezon an depi premye hub aktif la ; kolis la pase nan machin eta yo.'),
  ('c-liv-en-retard', '{nombre} livraison(s) en retard.', '{nombre} late delivery(ies).', '{nombre} entrega(s) con retraso.', '{nombre} livrezon an reta.'),
  ('c-creneau-MORNING', 'Matin', 'Morning', 'Mañana', 'Maten'),
  ('c-creneau-AFTERNOON', 'Après-midi', 'Afternoon', 'Tarde', 'Apremidi'),
  ('c-dedouane-le', 'dédouané le {date}', 'cleared {date}', 'despachado el {date}', 'dedwane {date}'),
  ('c-resolution', 'Résolution', 'Resolution', 'Resolución', 'Rezolisyon'),
  ('c-notif-intro', "Le journal des messages envoyés aux clients. Le contenu d'un message n'est jamais affiché ici : un code de livraison peut s'y trouver.", 'The log of messages sent to customers. The content of a message is never shown here: a delivery code may be in it.', 'El registro de mensajes enviados a los clientes. El contenido de un mensaje nunca se muestra aquí: puede incluir un código de entrega.', 'Jounal mesaj yo voye bay kliyan yo. Kontni yon mesaj pa janm afiche isit la : yon kòd livrezon ka ladan l.'),
  ('c-cli-intro', 'Les clients inscrits, leurs colis et ce qu\'ils doivent. Un compte d\'équipe qui porte encore un colis d\'avant la règle « équipe ≠ clientèle » est signalé.', 'Registered customers, their parcels and what they owe. A team account that still carries a parcel from before the "team ≠ customers" rule is flagged.', 'Los clientes registrados, sus paquetes y lo que deben. Se señala una cuenta del equipo que aún lleva un paquete anterior a la regla «equipo ≠ clientela».', 'Kliyan ki enskri yo, kolis yo ak sa yo dwe. Yon kont ekip ki toujou pote yon kolis ki soti anvan règ « ekip ≠ kliyan » an make.'),
  ('c-compte-equipe', "Compte d'équipe", 'Team account', 'Cuenta del equipo', 'Kont ekip'),
  ('c-voir-colis', 'Voir les colis', 'See parcels', 'Ver paquetes', 'Wè kolis yo'),
  ('c-sup-intro', "Les tickets de support des clients : les plus anciens sans réponse d'abord. Ouvrez un ticket pour lire la conversation, répondre ou le fermer.", 'Customer support tickets: the oldest without an answer first. Open a ticket to read the conversation, answer or close it.', 'Los tickets de soporte de los clientes: primero los más antiguos sin respuesta. Abra un ticket para leer la conversación, responder o cerrarlo.', 'Tikè sipò kliyan yo : pi ansyen ki pa gen repons yo an premye. Louvri yon tikè pou li konvèsasyon an, reponn oswa fèmen l.'),
  ('c-auteur-client', 'Le client', 'The customer', 'El cliente', 'Kliyan an'),
  ('c-auteur-equipe', "L'équipe", 'The team', 'El equipo', 'Ekip la'),
  ('c-attend-depuis-h', 'attend depuis {nombre} h', 'waiting for {nombre} h', 'espera desde hace {nombre} h', 'ap tann depi {nombre} è'),
  ('c-fac-intro', 'Les factures émises (les brouillons ne figurent pas ici), avec leur solde. Les totaux ci-dessous suivent les filtres.', 'Issued invoices (drafts are not listed), with their balance. The totals below follow the filters.', 'Las facturas emitidas (los borradores no figuran aquí), con su saldo. Los totales siguientes siguen los filtros.', 'Fakti ki emèt yo (bouyon yo pa la), ak balans yo. Total ki anba yo swiv filt yo.'),
  ('c-totaux', 'Totaux', 'Totals', 'Totales', 'Total yo'),
  ('c-tot-facture', 'Facturé ({devise})', 'Invoiced ({devise})', 'Facturado ({devise})', 'Faktire ({devise})'),
  ('c-tot-impaye', 'Impayé ({devise})', 'Unpaid ({devise})', 'Impago ({devise})', 'Enpeye ({devise})'),
  ('c-tot-impaye-n', '{nombre} facture(s)', '{nombre} invoice(s)', '{nombre} factura(s)', '{nombre} fakti'),
  ('c-groupee', 'Groupée', 'Grouped', 'Agrupada', 'Gwoupe'),
  ('c-simple', 'Simple', 'Single', 'Simple', 'Senp'),
  ('c-avoir-de', 'avoir {montant}', 'credit {montant}', 'abono {montant}', 'kredi {montant}'),
  ('c-rembourse-de', 'remboursé {montant}', 'refunded {montant}', 'reembolsado {montant}', 'ranbouse {montant}'),
  ('c-echeance', 'échéance {date}', 'due {date}', 'vence {date}', 'echeyans {date}'),
  ('c-pai-intro', 'Les paiements encaissés, les remboursements (en négatif) et les avoirs. Un remboursement montre son motif, qui reste interne.', 'Payments received, refunds (as negatives) and credit notes. A refund shows its reason, which stays internal.', 'Los pagos cobrados, los reembolsos (en negativo) y los abonos. Un reembolso muestra su motivo, que sigue siendo interno.', 'Peman yo resevwa, ranbousman yo (an negatif) ak kredi yo. Yon ranbousman montre rezon li, ki rete entèn.'),
  ('c-pai-encaisse', 'Encaissé (USD)', 'Collected (USD)', 'Cobrado (USD)', 'Ankese (USD)'),
  ('c-pai-rembourse', 'Remboursé (USD)', 'Refunded (USD)', 'Reembolsado (USD)', 'Ranbouse (USD)'),
  ('c-equivalent-usd', 'soit {montant}', 'i.e. {montant}', 'es decir {montant}', 'sa vle di {montant}'),
  ('c-usr-intro', "Les comptes de l'équipe et leurs rôles. Pour en changer un, passez par « Équipe » dans le menu de gestion.", 'Team accounts and their roles. To change one, go through “Team” in the management menu.', 'Las cuentas del equipo y sus roles. Para cambiar una, use «Equipo» en el menú de gestión.', 'Kont ekip la ak wòl yo. Pou chanje youn, pase pa « Ekip » nan meni jesyon an.'),
  ('c-chauffeur', 'Chauffeur', 'Driver', 'Conductor', 'Chofè'),
  ('c-aucun-droit', 'Aucun droit', 'No permissions', 'Sin permisos', 'Pa gen dwa'),
  ('c-aud-intro', "Qui a fait quoi, quand, avec le statut d'avant et d'après. Le journal ne se modifie ni ne se supprime.", 'Who did what, when, with the status before and after. The log can be neither edited nor deleted.', 'Quién hizo qué, cuándo, con el estado anterior y posterior. El registro no se puede modificar ni borrar.', 'Ki moun ki fè kisa, kilè, ak eta anvan an ak apre a. Pa gen moun ki ka modifye oswa efase jounal la.'),
  ('c-aud-action-aide', 'Début de l\'action, ex. ticket.', 'Start of the action, e.g. ticket.', 'Inicio de la acción, p. ej. ticket.', 'Kòmansman aksyon an, pa egzanp ticket.'),
  ('c-reg-intro', 'Un coup d\'œil sur la configuration du noyau logistique. Ces réglages se modifient par les fonctions de la direction, pas ici.', 'A glance at the logistics core configuration. These settings are changed through management functions, not here.', 'Un vistazo a la configuración del núcleo logístico. Estos ajustes se modifican con las funciones de la dirección, no aquí.', 'Yon kout je sou konfigirasyon nwayo lojistik la. Paramèt sa yo chanje pa fonksyon direksyon yo, pa isit la.'),
  ('c-reg-organisation', 'Organisation', 'Organization', 'Organización', 'Òganizasyon'),
  ('c-reg-nom', 'Nom', 'Name', 'Nombre', 'Non'),
  ('c-reg-devise', 'Devise par défaut', 'Default currency', 'Moneda por defecto', 'Lajan pa defo'),
  ('c-reg-succursales', 'Succursales', 'Branches', 'Sucursales', 'Branch'),
  ('c-reg-entrepots', 'Entrepôts', 'Warehouses', 'Almacenes', 'Depo'),
  ('c-reg-modes', 'Modes de transport', 'Transport modes', 'Modos de transporte', 'Mòd transpò'),
  ('c-reg-tarification', 'Tarification', 'Pricing', 'Tarificación', 'Tarifikasyon'),
  ('c-reg-grilles', 'Grilles tarifaires actives', 'Active rate cards', 'Tarifas activas', 'Grid tarif aktif'),
  ('c-reg-zones-tarif', 'Zones tarifaires actives', 'Active pricing zones', 'Zonas tarifarias activas', 'Zòn tarif aktif'),
  ('c-reg-surtaxes', 'Surtaxes actives', 'Active surcharges', 'Recargos activos', 'Sipleman aktif'),
  ('c-reg-regles', 'Règles actives', 'Active rules', 'Reglas activas', 'Règ aktif'),
  ('c-reg-taxes', 'Taxes actives', 'Active taxes', 'Impuestos activos', 'Taks aktif'),
  ('c-reg-frais', 'Frais de service', 'Service fees', 'Gastos de servicio', 'Frè sèvis'),
  ('c-reg-taux', 'Taux de change', 'Exchange rates', 'Tipos de cambio', 'To chanj'),
  ('c-depuis', 'depuis le {date}', 'since {date}', 'desde el {date}', 'depi {date}'),
  ('c-reg-livraison', 'Dernier kilomètre', 'Last mile', 'Última milla', 'Dènye kilomèt'),
  ('c-reg-zones', 'Zones de livraison', 'Delivery zones', 'Zonas de entrega', 'Zòn livrezon'),
  ('c-reg-vehicules', 'Véhicules actifs', 'Active vehicles', 'Vehículos activos', 'Machin aktif'),
  ('c-reg-chauffeurs', 'Chauffeurs actifs', 'Active drivers', 'Conductores activos', 'Chofè aktif'),
  ('c-reg-evenements', 'File des événements', 'Event queue', 'Cola de eventos', 'Fil evènman yo'),
  ('c-reg-en-attente', 'En attente', 'Pending', 'Pendiente', 'An atant'),
  ('c-reg-en-echec', 'En échec définitif', 'Permanently failed', 'Fallidos definitivamente', 'Echwe nèt'))

# ---- la santé des envois (phase 13) ----
a(('c-sante-titre', 'Santé des envois', 'Delivery health', 'Estado de los envíos', 'Sante voye yo'),
  ('c-sante-attente', 'En attente', 'Pending', 'Pendiente', 'An atant'),
  ('c-sante-en-cours', 'En cours d\'envoi', 'Being sent', 'Enviándose', 'Ap voye'),
  ('c-sante-envoyees', 'Envoyées (24 h)', 'Sent (24 h)', 'Enviadas (24 h)', 'Voye (24 è)'),
  ('c-sante-relances', 'Nouveaux essais (24 h)', 'Retries (24 h)', 'Reintentos (24 h)', 'Nouvo esè (24 è)'),
  ('c-sante-echecs', 'Échecs (24 h)', 'Failures (24 h)', 'Fallos (24 h)', 'Echèk (24 è)'),
  ('c-sante-file', 'File des événements : {attente} en attente, {mortes} en échec définitif.', 'Event queue: {attente} waiting, {mortes} permanently failed.', 'Cola de eventos: {attente} en espera, {mortes} con fallo definitivo.', 'Fil evènman yo : {attente} ap tann, {mortes} echwe nèt.'),
  ('c-sante-erreurs', 'Dernières erreurs (nettoyées de tout secret)', 'Latest errors (cleaned of any secret)', 'Últimos errores (sin ningún secreto)', 'Dènye erè yo (san okenn sekrè)'),
  ('c-sante-RETRY', 'Nouvel essai prévu', 'Retry planned', 'Reintento previsto', 'Nouvo esè prevwa'),
  ('c-sante-FAILED', 'Échec définitif', 'Permanent failure', 'Fallo definitivo', 'Echèk nèt'))

# ---- entrepôt ---------------------------------------------------------------------------------------------------------------------------
a(('c-ent-colis', 'Colis présents', 'Parcels present', 'Paquetes presentes', 'Kolis ki la'),
  ('c-ent-recus', "Reçus aujourd'hui", 'Received today', 'Recibidos hoy', 'Resevwa jodi a'),
  ('c-ent-scans', "Scans d'aujourd'hui", "Today's scans", 'Escaneos de hoy', 'Eskanè jodi a'),
  ('c-ent-refuses', '{nombre} refusé(s)', '{nombre} rejected', '{nombre} rechazado(s)', '{nombre} refize'),
  ('c-ent-incidents', 'Incidents ouverts', 'Open issues', 'Incidencias abiertas', 'Pwoblèm ouvè'),
  ('c-ent-emplacements', 'Emplacements', 'Locations', 'Ubicaciones', 'Plas'),
  ('c-ent-vide', 'Aucun entrepôt actif.', 'No active warehouse.', 'Ningún almacén activo.', 'Pa gen okenn depo aktif.'),
  ('c-ent-derniers-scans', 'Derniers scans', 'Latest scans', 'Últimos escaneos', 'Dènye eskanè yo'),
  ('c-ent-aucun-scan', 'Aucun scan enregistré.', 'No scan recorded.', 'Ningún escaneo registrado.', 'Pa gen okenn eskanè anrejistre.'))

# ---- les fiches : colis, ticket, traitement des demandes ------------------------------------------------------------------------------
a(('c-fiche-titre', 'Fiche du colis', 'Parcel file', 'Ficha del paquete', 'Fich kolis la'),
  ('c-fiche-adresse', 'Adresse de livraison', 'Delivery address', 'Dirección de entrega', 'Adrès livrezon'),
  ('c-fiche-expediteur', 'Expéditeur', 'Sender', 'Remitente', 'Ekspeditè'),
  ('c-fiche-destinataire', 'Destinataire', 'Recipient', 'Destinatario', 'Destinatè'),
  ('c-fiche-valeur', 'Valeur déclarée', 'Declared value', 'Valor declarado', 'Valè deklare'),
  ('c-fiche-etat', 'État du colis', 'Parcel condition', 'Estado del paquete', 'Kondisyon kolis la'),
  ('c-fiche-autorite', 'Source du statut', 'Status source', 'Fuente del estado', 'Sous eta a'),
  ('c-fiche-expeditions', 'Expéditions', 'Shipments', 'Envíos', 'Ekspedisyon'),
  ('c-fiche-livraisons', 'Livraisons', 'Deliveries', 'Entregas', 'Livrezon'),
  ('c-fiche-incidents', 'Incidents', 'Issues', 'Incidencias', 'Pwoblèm'),
  ('c-fiche-journal', 'Journal complet (événements internes compris)', 'Full log (internal events included)', 'Registro completo (eventos internos incluidos)', 'Jounal konplè (evènman entèn yo enkli)'),
  ('c-fiche-journal-vide', 'Aucun événement enregistré.', 'No event recorded.', 'Ningún evento registrado.', 'Pa gen okenn evènman anrejistre.'),
  ('c-fiche-scans', 'Derniers scans', 'Latest scans', 'Últimos escaneos', 'Dènye eskanè yo'),
  ('c-fiche-messages', 'Conversation', 'Conversation', 'Conversación', 'Konvèsasyon'),
  ('c-motif', 'Motif', 'Reason', 'Motivo', 'Rezon'),
  ('c-ticket-titre', 'Ticket de support', 'Support ticket', 'Ticket de soporte', 'Tikè sipò'),
  ('c-tkcat', 'Catégorie', 'Category', 'Categoría', 'Kategori'),
  ('c-reponse', 'Votre réponse au client', 'Your reply to the customer', 'Su respuesta al cliente', 'Repons ou bay kliyan an'),
  ('c-reponse-vide', 'Écrivez une réponse avant de l\'envoyer.', 'Write a reply before sending it.', 'Escriba una respuesta antes de enviarla.', 'Ekri yon repons anvan ou voye l.'),
  ('c-reponse-envoyee', 'Réponse envoyée.', 'Reply sent.', 'Respuesta enviada.', 'Repons voye.'),
  ('c-fermer-ticket', 'Fermer le ticket', 'Close the ticket', 'Cerrar el ticket', 'Fèmen tikè a'),
  ('c-tk-ferme', 'Le ticket est fermé.', 'The ticket is closed.', 'El ticket está cerrado.', 'Tikè a fèmen.'),
  ('c-ticket-ferme', 'Ticket fermé.', 'Ticket closed.', 'Ticket cerrado.', 'Tikè fèmen.'),
  ('c-traiter', 'Traiter', 'Process', 'Tramitar', 'Trete'),
  ('c-trait-enl-titre', "Traiter la demande d'enlèvement", 'Process the pickup request', 'Tramitar la solicitud de recogida', 'Trete demann ranmasaj la'),
  ('c-trait-liv-titre', 'Traiter la demande de livraison', 'Process the delivery request', 'Tramitar la solicitud de entrega', 'Trete demann livrezon an'),
  ('c-trait-enl-intro', "Approuver crée une mission d'enlèvement pour la date choisie ; refuser demande un message, que le client lira.", 'Approving creates a pickup task for the chosen date; refusing requires a message, which the customer will read.', 'Aprobar crea una misión de recogida para la fecha elegida; rechazar exige un mensaje, que el cliente leerá.', 'Apwouve kreye yon misyon ranmasaj pou dat ou chwazi a ; refize mande yon mesaj, kliyan an pral li l.'),
  ('c-trait-liv-intro', 'Approuver crée la livraison avec les colis de la demande ; refuser demande un message, que le client lira.', 'Approving creates the delivery with the parcels of the request; refusing requires a message, which the customer will read.', 'Aprobar crea la entrega con los paquetes de la solicitud; rechazar exige un mensaje, que el cliente leerá.', 'Apwouve kreye livrezon an ak kolis demann lan ; refize mande yon mesaj, kliyan an pral li l.'),
  ('c-trait-date', 'Autre date (facultatif)', 'Another date (optional)', 'Otra fecha (opcional)', 'Lòt dat (opsyonèl)'),
  ('c-trait-message', 'Message au client', 'Message to the customer', 'Mensaje al cliente', 'Mesaj pou kliyan an'),
  ('c-trait-message-aide', 'Obligatoire pour refuser. 500 caractères au plus.', 'Required to refuse. 500 characters at most.', 'Obligatorio para rechazar. 500 caracteres como máximo.', 'Obligatwa pou refize. 500 karaktè o maksimòm.'),
  ('c-trait-motif-obligatoire', 'Un message au client est obligatoire pour refuser.', 'A message to the customer is required to refuse.', 'Se exige un mensaje al cliente para rechazar.', 'Yon mesaj pou kliyan an obligatwa pou refize.'),
  ('c-approuver', 'Approuver', 'Approve', 'Aprobar', 'Apwouve'),
  ('c-refuser', 'Refuser', 'Refuse', 'Rechazar', 'Refize'),
  ('c-trait-approuvee', 'Demande approuvée.', 'Request approved.', 'Solicitud aprobada.', 'Demann apwouve.'),
  ('c-trait-refusee', 'Demande refusée.', 'Request refused.', 'Solicitud rechazada.', 'Demann refize.'))

# ---- les valeurs que la base connaît --------------------------------------------------------------------------------------------------
famille('c-colis-', {
    'CREATED': ('Enregistré', 'Registered', 'Registrado', 'Anrejistre'), 'RECEIVED': ('Reçu', 'Received', 'Recibido', 'Resevwa'), 'VERIFIED': ('Vérifié', 'Checked', 'Verificado', 'Verifye'),
    'STORED': ('Rangé', 'Stored', 'Almacenado', 'Ranje'), 'CONSOLIDATION_PENDING': ('En attente de consolidation', 'Awaiting consolidation', 'Pendiente de consolidación', 'Ap tann gwoupman'),
    'CONSOLIDATED': ('Consolidé', 'Consolidated', 'Consolidado', 'Gwoupe'), 'READY_FOR_EXPORT': ('Prêt à partir', 'Ready to leave', 'Listo para salir', 'Pare pou pati'),
    'IN_TRANSIT': ('En transit', 'In transit', 'En tránsito', 'An tranzit'), 'ARRIVED': ('Arrivé', 'Arrived', 'Llegado', 'Rive'), 'CUSTOMS_PROCESSING': ('En cours de dédouanement', 'In customs clearance', 'En despacho aduanero', 'Ap pase nan dwàn'),
    'CUSTOMS_CLEARED': ('Dédouané', 'Cleared', 'Despachado', 'Dedwane'), 'AT_DESTINATION_HUB': ('Au hub de destination', 'At the destination hub', 'En el hub de destino', 'Nan hub destinasyon an'),
    'DELIVERY_ASSIGNED': ('Affecté à une livraison', 'Assigned to a delivery', 'Asignado a una entrega', 'Afekte nan yon livrezon'), 'OUT_FOR_DELIVERY': ('En livraison', 'Out for delivery', 'En reparto', 'Nan livrezon'),
    'DELIVERED': ('Livré', 'Delivered', 'Entregado', 'Livre'), 'ON_HOLD': ('Retenu', 'On hold', 'Retenido', 'Kenbe'), 'DAMAGED': ('Endommagé', 'Damaged', 'Dañado', 'Domaje'), 'LOST': ('Perdu', 'Lost', 'Perdido', 'Pèdi'),
    'CANCELLED': ('Annulé', 'Cancelled', 'Cancelado', 'Anile'), 'RETURNED': ('Retourné', 'Returned', 'Devuelto', 'Retounen')})
famille('c-exp-', {
    'ACTIVE': ('En cours (non clôturées)', 'In progress (not closed)', 'En curso (no cerradas)', 'An kou (poko fèmen)'), 'DRAFT': ('Brouillon', 'Draft', 'Borrador', 'Bouyon'), 'READY': ('Prête', 'Ready', 'Lista', 'Pare'),
    'DISPATCHED': ('Expédiée', 'Dispatched', 'Despachada', 'Ekspedye'), 'IN_TRANSIT': ('En transit', 'In transit', 'En tránsito', 'An tranzit'), 'ARRIVED': ('Arrivée à destination', 'Arrived at destination', 'Llegada a destino', 'Rive nan destinasyon'),
    'CUSTOMS_PROCESSING': ('En douane', 'In customs', 'En aduana', 'Nan dwàn'), 'CUSTOMS_CLEARED': ('Dédouanée', 'Cleared', 'Despachada', 'Dedwane'), 'AT_HUB': ('Au hub', 'At the hub', 'En el hub', 'Nan hub la'),
    'CLOSED': ('Clôturée', 'Closed', 'Cerrada', 'Fèmen'), 'CANCELLED': ('Annulée', 'Cancelled', 'Cancelada', 'Anile')})
famille('c-trans-', {'PLANNED': ('Planifié', 'Scheduled', 'Planificado', 'Planifye'), 'DEPARTED': ('Parti', 'Departed', 'Salido', 'Pati'), 'ARRIVED': ('Arrivé', 'Arrived', 'Llegado', 'Rive'), 'CANCELLED': ('Annulé', 'Cancelled', 'Cancelado', 'Anile')})
famille('c-miss-', {
    'CREATED': ('Créée', 'Created', 'Creada', 'Kreye'), 'ASSIGNED': ('Attribuée', 'Assigned', 'Asignada', 'Bay yon chofè'), 'ACCEPTED': ('Acceptée', 'Accepted', 'Aceptada', 'Aksepte'), 'STARTED': ('En cours', 'In progress', 'En curso', 'An kou'),
    'COMPLETED': ('Terminée', 'Completed', 'Completada', 'Fini'), 'FAILED': ('Échouée', 'Failed', 'Fallida', 'Echwe'), 'CANCELLED': ('Annulée', 'Cancelled', 'Cancelada', 'Anile')})
famille('c-chauf-', {'ACTIVE': ('Actif', 'Active', 'Activo', 'Aktif'), 'ON_LEAVE': ('En congé', 'On leave', 'De permiso', 'Nan konje'), 'INACTIVE': ('Inactif', 'Inactive', 'Inactivo', 'Pa aktif')})
famille('c-dou-', {
    'DRAFT': ('Brouillon', 'Draft', 'Borrador', 'Bouyon'), 'SUBMITTED': ('Déposée', 'Submitted', 'Presentada', 'Depoze'), 'UNDER_REVIEW': ("En cours d'examen", 'Under review', 'En revisión', 'Ap egzamine'),
    'CLEARED': ('Dédouanée', 'Cleared', 'Despachada', 'Dedwane'), 'REJECTED': ('Refusée', 'Rejected', 'Rechazada', 'Refize')})
famille('c-cons-', {'OPEN': ('Ouverte', 'Open', 'Abierta', 'Ouvè'), 'CLOSED': ('Fermée', 'Closed', 'Cerrada', 'Fèmen'), 'CANCELLED': ('Annulée', 'Cancelled', 'Cancelada', 'Anile')})
famille('c-incst-', {
    'ACTIVE': ('Actifs (ouverts ou en cours)', 'Active (open or in progress)', 'Activos (abiertos o en curso)', 'Aktif (ouvè oswa an kou)'), 'OPEN': ('Ouvert', 'Open', 'Abierto', 'Ouvè'), 'IN_PROGRESS': ('En cours', 'In progress', 'En curso', 'An kou'),
    'RESOLVED': ('Résolu', 'Resolved', 'Resuelto', 'Rezoud'), 'CANCELLED': ('Annulé', 'Cancelled', 'Cancelado', 'Anile')})
famille('c-grav-', {'HIGH': ('Grave', 'Serious', 'Grave', 'Grav'), 'MEDIUM': ('Moyenne', 'Medium', 'Media', 'Mwayen'), 'LOW': ('Faible', 'Low', 'Baja', 'Ba')})
famille('c-inc-', {
    'DAMAGED': ('Colis endommagé', 'Damaged parcel', 'Paquete dañado', 'Kolis domaje'), 'PROHIBITED_ITEM': ('Article interdit', 'Prohibited item', 'Artículo prohibido', 'Atik entèdi'), 'UNKNOWN_PARCEL': ('Colis inconnu', 'Unknown parcel', 'Paquete desconocido', 'Kolis enkoni'),
    'FORGED_LABEL': ('Étiquette falsifiée', 'Forged label', 'Etiqueta falsificada', 'Etikèt fo'), 'WRONG_WAREHOUSE': ('Mauvais entrepôt', 'Wrong warehouse', 'Almacén equivocado', 'Move depo'), 'NO_CUSTOMER': ('Colis sans client', 'Parcel without a customer', 'Paquete sin cliente', 'Kolis san kliyan'),
    'CUSTOMER_ABSENT': ('Client absent', 'Customer absent', 'Cliente ausente', 'Kliyan absan'), 'WRONG_ADDRESS': ('Adresse erronée', 'Wrong address', 'Dirección errónea', 'Move adrès'), 'REFUSED': ('Colis refusé', 'Parcel refused', 'Paquete rechazado', 'Kolis refize'),
    'VEHICLE_PROBLEM': ('Problème de véhicule', 'Vehicle problem', 'Problema de vehículo', 'Pwoblèm machin'), 'PAYMENT_PROBLEM': ('Problème de paiement', 'Payment problem', 'Problema de pago', 'Pwoblèm peman'), 'OTHER': ('Autre', 'Other', 'Otro', 'Lòt')})
famille('c-nst-', {'PENDING': ('En attente', 'Pending', 'Pendiente', 'An atant'), 'SENT': ('Envoyée', 'Sent', 'Enviada', 'Voye'), 'FAILED': ('Échec', 'Failed', 'Fallida', 'Echwe'), 'SKIPPED': ('Non envoyée', 'Skipped', 'Omitida', 'Pa voye')})
famille('c-canal-', {'in_app': ("Dans l'espace client", 'In the customer area', 'En el espacio de cliente', 'Nan espas kliyan an'), 'email': ('E-mail', 'E-mail', 'Correo electrónico', 'Imèl'), 'push': ('Notification push', 'Push notification', 'Notificación push', 'Notifikasyon push'),
                     'sms': ('SMS', 'SMS', 'SMS', 'SMS'), 'whatsapp': ('WhatsApp', 'WhatsApp', 'WhatsApp', 'WhatsApp')})
famille('c-tk-', {'ACTIVE': ('Actifs (non fermés)', 'Active (not closed)', 'Activos (no cerrados)', 'Aktif (pa fèmen)'), 'OPEN': ("Ouvert (attend l'équipe)", 'Open (waiting for the team)', 'Abierto (espera al equipo)', 'Ouvè (ap tann ekip la)'),
                  'ANSWERED': ('Répondu', 'Answered', 'Respondido', 'Reponn'), 'CLOSED': ('Fermé', 'Closed', 'Cerrado', 'Fèmen')})
famille('c-tkcat-', {'PARCEL': ('Un colis', 'A parcel', 'Un paquete', 'Yon kolis'), 'INVOICE': ('Une facture', 'An invoice', 'Una factura', 'Yon fakti'), 'PICKUP': ('Un enlèvement', 'A pickup', 'Una recogida', 'Yon ranmasaj'),
                     'DELIVERY': ('Une livraison', 'A delivery', 'Una entrega', 'Yon livrezon'), 'ACCOUNT': ('Un compte', 'An account', 'Una cuenta', 'Yon kont'), 'OTHER': ('Autre sujet', 'Other topic', 'Otro tema', 'Lòt sijè')})
famille('c-fact-', {
    'UNPAID': ('Impayées (avec un solde)', 'Unpaid (with a balance)', 'Impagas (con saldo)', 'Enpeye (ak yon balans)'), 'ISSUED': ('Émise', 'Issued', 'Emitida', 'Emèt'), 'PARTIALLY_PAID': ('Partiellement payée', 'Partially paid', 'Pagada parcialmente', 'Peye yon pati'),
    'PAID': ('Payée', 'Paid', 'Pagada', 'Peye'), 'OVERDUE': ('En retard de paiement', 'Overdue', 'Vencida', 'An reta'), 'CANCELLED': ('Annulée', 'Cancelled', 'Cancelada', 'Anile'), 'REFUNDED': ('Remboursée', 'Refunded', 'Reembolsada', 'Ranbouse')})
famille('c-paie-', {'PAYMENT': ('Paiement', 'Payment', 'Pago', 'Peman'), 'REFUND': ('Remboursement', 'Refund', 'Reembolso', 'Ranbousman'), 'CREDIT': ('Avoir', 'Credit note', 'Abono', 'Kredi')})
famille('c-moyen-', {'CASH': ('Espèces', 'Cash', 'Efectivo', 'Lajan kach'), 'CARD': ('Carte', 'Card', 'Tarjeta', 'Kat'), 'TRANSFER': ('Virement', 'Transfer', 'Transferencia', 'Transfè'), 'MOBILE_MONEY': ('Argent mobile', 'Mobile money', 'Dinero móvil', 'Lajan mobil'),
                     'CHECK': ('Chèque', 'Check', 'Cheque', 'Chèk'), 'OTHER': ('Autre', 'Other', 'Otro', 'Lòt')})
famille('c-role-', {'admin': ('Administrateur', 'Administrator', 'Administrador', 'Administratè'), 'manager': ('Gérant', 'Manager', 'Gerente', 'Jeran'), 'employee': ('Employé', 'Employee', 'Empleado', 'Anplwaye'),
                    'INACTIVE': ('Comptes désactivés', 'Deactivated accounts', 'Cuentas desactivadas', 'Kont dezaktive')})
famille('c-etape-', {'requested': ('Demandé', 'Requested', 'Solicitado', 'Mande'), 'scheduled': ('Planifié', 'Scheduled', 'Planificado', 'Planifye'), 'on_the_way': ('En route', 'On the way', 'En camino', 'Sou wout'),
                     'completed': ('Terminé', 'Completed', 'Completado', 'Fini'), 'delivered': ('Livré', 'Delivered', 'Entregado', 'Livre'), 'missed': ('Manqué', 'Missed', 'Fallido', 'Rate'), 'rejected': ('Refusé', 'Rejected', 'Rechazado', 'Refize'),
                     'cancelled': ('Annulé', 'Cancelled', 'Cancelado', 'Anile')})
# Le poste de scan du bureau (assets/js/ses-poste.js, phase 15)
a(('c-poste-intro', "Branchez un scanner USB : il lit ici, sans clic. Chaque lecture part vers la base, qui rend son verdict.", 'Plug in a USB scanner: it reads here, no click needed. Each read goes to the database, which returns its verdict.',
   'Conecte un escáner USB: lee aquí, sin hacer clic. Cada lectura va a la base de datos, que da su veredicto.', 'Branche yon eskanè USB : li li isit la, san klike. Chak lekti ale nan baz done a, ki bay desizyon li.'),
  ('c-poste-sans-profil', "Votre compte n'a pas le profil entrepôt : il faut le droit de faire avancer les colis et une succursale qui n'est pas un hub. Demandez-le à la direction.",
   'Your account does not have the warehouse profile: it needs the right to move parcels forward and a branch that is not a hub. Ask management.',
   'Su cuenta no tiene el perfil de almacén: necesita el derecho de avanzar paquetes y una sucursal que no sea un hub. Pídalo a la dirección.',
   'Kont ou pa gen pwofil depo a : li bezwen dwa pou fè kolis avanse ak yon siksisal ki pa yon hub. Mande direksyon an li.'),
  ('c-poste-entrepot', 'Entrepôt du poste', 'Station warehouse', 'Almacén del puesto', 'Depo pòs la'),
  ('c-poste-intention', 'Ce que vous faites', 'What you are doing', 'Lo que está haciendo', 'Sa w ap fè'),
  ('c-poste-code', 'Numéro ou code lu', 'Number or scanned code', 'Número o código leído', 'Nimewo oswa kòd ki li'),
  ('c-poste-lire', 'Envoyer', 'Send', 'Enviar', 'Voye'),
  ('c-poste-pret', 'Prêt : scannez un colis.', 'Ready: scan a parcel.', 'Listo: escanee un paquete.', 'Pare : eskane yon kolis.'),
  ('c-poste-envoi', 'Envoi…', 'Sending…', 'Enviando…', 'Ap voye…'),
  ('c-poste-pas-parti', "Pas parti", 'Not sent', 'No enviado', 'Pa pati'),
  ('c-poste-col-heure', 'Heure', 'Time', 'Hora', 'Lè'),
  ('c-poste-col-lecteur', 'Lecteur', 'Reader', 'Lector', 'Lektè'),
  ('c-poste-col-code', 'Code', 'Code', 'Código', 'Kòd'),
  ('c-poste-etiquette', 'Étiquette', 'Label', 'Etiqueta', 'Etikèt'),
  ('c-poste-etiquette-absente', "Ce colis n'a pas d'étiquette dans le registre des colis.", 'This parcel has no label in the parcel register.', 'Este paquete no tiene etiqueta en el registro de paquetes.', 'Kolis sa a pa gen etikèt nan rejis kolis yo.'),
  ('c-poste-session', 'Lectures de cette session', 'Reads in this session', 'Lecturas de esta sesión', 'Lekti sesyon sa a'),
  ('c-poste-aucune', 'Aucune lecture pour le moment.', 'No read yet.', 'Ninguna lectura por ahora.', 'Pa gen okenn lekti pou kounye a.'),
  ('c-poste-compte', '{nombre} lecture(s), dont {acceptees} acceptée(s)', '{nombre} read(s), {acceptees} accepted', '{nombre} lectura(s), {acceptees} aceptada(s)', '{nombre} lekti, {acceptees} aksepte'),
  ('c-poste-exporter', 'Exporter (CSV)', 'Export (CSV)', 'Exportar (CSV)', 'Ekspòte (CSV)'),
  ('c-poste-importer', 'Importer une liste', 'Import a list', 'Importar una lista', 'Enpòte yon lis'),
  ('c-poste-import-vide', 'Aucun numéro lisible dans ce fichier.', 'No readable number in this file.', 'Ningún número legible en este archivo.', 'Pa gen okenn nimewo ki ka li nan fichye sa a.'),
  ('c-poste-import-trop', 'Fichier trop gros (1 Mo au plus).', 'File too large (1 MB at most).', 'Archivo demasiado grande (1 MB como máximo).', 'Fichye a twò gwo (1 Mo pi plis).'),
  ('c-poste-import-confirmer', '{nombre} numéro(s) à scanner, intention « {intention} ». Continuer ?', '{nombre} number(s) to scan, purpose "{intention}". Continue?',
   '{nombre} número(s) por escanear, intención «{intention}». ¿Continuar?', '{nombre} nimewo pou eskane, entansyon « {intention} ». Kontinye ?'),
  ('c-poste-imprimer', 'Imprimer le bordereau', 'Print the slip', 'Imprimir el comprobante', 'Enprime bòdwo a'),
  ('c-poste-bordereau', 'Bordereau de scan', 'Scan slip', 'Comprobante de escaneo', 'Bòdwo eskanè'),
  ('c-poste-son', 'Son en cas de refus', 'Sound on rejection', 'Sonido en caso de rechazo', 'Son lè gen refi'),
  ('c-poste-notif', 'Notifications du bureau', 'Desktop notifications', 'Notificaciones de escritorio', 'Notifikasyon biwo'),
  ('c-poste-notif-refusees', 'Le navigateur refuse les notifications : autorisez-les dans ses réglages.', 'The browser blocks notifications: allow them in its settings.',
   'El navegador bloquea las notificaciones: permítalas en su configuración.', 'Navigatè a bloke notifikasyon yo : otorize yo nan paramèt li.'),
  ('c-poste-notif-titre', 'Speed Express — activité', 'Speed Express — activity', 'Speed Express — actividad', 'Speed Express — aktivite'),
  ('c-poste-notif-corps', 'Du nouveau dans le centre de commande.', 'Something changed in the command center.', 'Hay novedades en el centro de mando.', 'Gen bagay ki chanje nan sant kòmandman an.'),
  ('c-poste-installer', 'Installer sur cet ordinateur', 'Install on this computer', 'Instalar en esta computadora', 'Enstale sou òdinatè sa a'),
  ('c-poste-installer-aide', "Sur Windows ou Mac : Chrome ou Edge, menu « Installer » ; Safari sur Mac, menu Fichier, Ajouter au Dock. Le tableau de bord s'ouvre alors dans sa propre fenêtre.",
   'On Windows or Mac: Chrome or Edge, "Install" menu; Safari on Mac, File menu, Add to Dock. The dashboard then opens in its own window.',
   'En Windows o Mac: Chrome o Edge, menú «Instalar»; Safari en Mac, menú Archivo, Añadir al Dock. El panel se abre entonces en su propia ventana.',
   'Sou Windows oswa Mac : Chrome oswa Edge, meni « Enstale » ; Safari sou Mac, meni Fichye, Ajoute nan Dock. Tablo a ap louvri nan pwòp fenèt li.'))
famille('c-poste-genre-', {'barcode': ('Scanner', 'Scanner', 'Escáner', 'Eskanè'), 'qr': ('QR', 'QR', 'QR', 'QR'), 'manual': ('Saisie', 'Typed', 'Tecleado', 'Tape'), 'unknown': ('—', '—', '—', '—')})
# L'analytique (assets/js/ses-analytique.js, phase 16)
a(('c-an-intro', "Les chiffres du jour à l'année, calculés par la base à partir des journaux. Chaque rapport dit de quels calculs il vient ; un jour jamais calculé est signalé, jamais compté zéro.",
   'Figures from day to year, computed by the database from its logs. Each report says which runs it comes from; a day never computed is flagged, never counted as zero.',
   'Las cifras del día al año, calculadas por la base de datos a partir de sus registros. Cada informe indica de qué cálculos proviene; un día nunca calculado se señala, nunca se cuenta como cero.',
   'Chif yo depi jou rive ane, baz done a kalkile yo apati jounal li yo. Chak rapò di ki kalkil li soti ; yon jou ki pa janm kalkile siyale, li pa janm konte zewo.'),
  ('c-an-grain', 'Regrouper par', 'Group by', 'Agrupar por', 'Gwoupe pa'),
  ('c-an-du', 'Du', 'From', 'Desde', 'Soti'),
  ('c-an-au', 'Au', 'To', 'Hasta', 'Jiska'),
  ('c-an-afficher', 'Afficher', 'Show', 'Mostrar', 'Montre'),
  ('c-an-exporter', 'Exporter (CSV)', 'Export (CSV)', 'Exportar (CSV)', 'Ekspòte (CSV)'),
  ('c-an-recalculer', 'Recalculer la période', 'Recompute the period', 'Recalcular el período', 'Rekalkile peryòd la'),
  ('c-an-calculer', 'Calculer ces jours', 'Compute these days', 'Calcular estos días', 'Kalkile jou sa yo'),
  ('c-an-recalcul-fait', 'Calcul enregistré : exécution n° {numero}.', 'Computation saved: run no. {numero}.', 'Cálculo registrado: ejecución n.º {numero}.', 'Kalkil anrejistre : egzekisyon nimewo {numero}.'),
  ('c-an-periode-invalide', 'Choisissez une date de début et une date de fin, dans cet ordre.', 'Choose a start date and an end date, in that order.', 'Elija una fecha de inicio y una de fin, en ese orden.', 'Chwazi yon dat kòmansman ak yon dat fen, nan lòd sa a.'),
  ('c-an-manquants', "{nombre} jour(s) de cette période n'ont jamais été calculés : ils ne comptent pas encore.", '{nombre} day(s) in this period were never computed: they do not count yet.',
   '{nombre} día(s) de este período nunca se calcularon: todavía no cuentan.', '{nombre} jou nan peryòd sa a pa janm kalkile : yo poko konte.'),
  ('c-an-provisoire', "Chiffres provisoires : la période inclut aujourd'hui.", 'Provisional figures: the period includes today.', 'Cifras provisionales: el período incluye hoy.', 'Chif pwovizwa : peryòd la gen ladan jodi a.'),
  ('c-an-provisoire-court', 'provisoire', 'provisional', 'provisional', 'pwovizwa'),
  ('c-an-source', 'Ce rapport vient des exécutions :', 'This report comes from runs:', 'Este informe proviene de las ejecuciones:', 'Rapò sa a soti nan egzekisyon sa yo :'),
  ('c-an-precedente', 'Période précédente : {valeur}', 'Previous period: {valeur}', 'Período anterior: {valeur}', 'Peryòd anvan an : {valeur}'),
  ('c-an-semaine', 'Semaine du {date}', 'Week of {date}', 'Semana del {date}', 'Semèn {date}'),
  ('c-an-trimestre', 'T{numero} {annee}', 'Q{numero} {annee}', 'T{numero} {annee}', 'T{numero} {annee}'),
  ('c-an-mesure', 'Mesure', 'Measure', 'Medida', 'Mezi'),
  ('c-an-dimension', 'Répartition', 'Breakdown', 'Desglose', 'Repatisyon'),
  ('c-an-valeur', 'Valeur', 'Value', 'Valor', 'Valè'),
  ('c-an-unite', 'Unité', 'Unit', 'Unidad', 'Inite'),
  ('c-an-executions', 'Exécutions (traçabilité)', 'Runs (traceability)', 'Ejecuciones (trazabilidad)', 'Egzekisyon (trasabilite)'),
  ('c-an-aucune', 'Aucune exécution pour le moment.', 'No run yet.', 'Ninguna ejecución por ahora.', 'Pa gen okenn egzekisyon pou kounye a.'),
  ('c-an-col-n', 'N°', 'No.', 'N.º', 'Nimewo'),
  ('c-an-col-periode', 'Période', 'Period', 'Período', 'Peryòd'),
  ('c-an-col-genere', 'Calculée le', 'Computed on', 'Calculada el', 'Kalkile le'),
  ('c-an-col-par', 'Par', 'By', 'Por', 'Pa'),
  ('c-an-col-lignes', 'Lignes', 'Rows', 'Filas', 'Liy'),
  ('c-an-col-empreinte', 'Empreinte', 'Checksum', 'Huella', 'Anprent'),
  ('c-an-verifier', 'Vérifier', 'Verify', 'Verificar', 'Verifye'),
  ('c-an-systeme', 'système', 'system', 'sistema', 'sistèm'))
famille('c-an-g-', {'day': ('Jour', 'Day', 'Día', 'Jou'), 'week': ('Semaine', 'Week', 'Semana', 'Semèn'), 'month': ('Mois', 'Month', 'Mes', 'Mwa'),
                    'quarter': ('Trimestre', 'Quarter', 'Trimestre', 'Trimès'), 'year': ('Année', 'Year', 'Año', 'Ane')})
famille('c-an-d-', {'ops': ('Activité', 'Operations', 'Actividad', 'Aktivite'), 'finance': ('Finance', 'Finance', 'Finanzas', 'Finans'), 'customers': ('Clientèle', 'Customers', 'Clientela', 'Kliyantèl')})
famille('c-an-v-', {'REPRODUCIBLE': ('Reproductible', 'Reproducible', 'Reproducible', 'Repwodiktib'), 'SOURCES_CHANGED': ('Les sources ont changé depuis', 'Sources changed since', 'Las fuentes cambiaron desde entonces', 'Sous yo chanje depi lè sa a'),
                    'COMPUTATION_CHANGED': ('Le calcul a changé', 'The computation changed', 'El cálculo cambió', 'Kalkil la chanje')})
famille('c-an-r-', {'delivery_success_pct': ('Livraisons réussies', 'Successful deliveries', 'Entregas exitosas', 'Livrezon ki reyisi'), 'avg_transit_hours': ('Délai moyen de transit', 'Average transit time', 'Tiempo medio de tránsito', 'Tan mwayèn transpò'),
                    'scan_rejection_pct': ('Scans refusés', 'Rejected scans', 'Escaneos rechazados', 'Eskanè ki refize'), 'collection_pct': ('Encaissé / facturé', 'Collected / billed', 'Cobrado / facturado', 'Touche / faktire')})
famille('c-an-m-', {
    'parcels_received': ('Colis reçus', 'Parcels received', 'Paquetes recibidos', 'Kolis resevwa'), 'parcels_delivered': ('Colis livrés', 'Parcels delivered', 'Paquetes entregados', 'Kolis livre'),
    'parcels_on_hold': ('Colis mis en attente', 'Parcels put on hold', 'Paquetes en espera', 'Kolis an atant'), 'parcels_damaged': ('Colis endommagés', 'Damaged parcels', 'Paquetes dañados', 'Kolis domaje'),
    'parcels_lost': ('Colis perdus', 'Lost parcels', 'Paquetes perdidos', 'Kolis pèdi'), 'parcels_returned': ('Colis retournés', 'Returned parcels', 'Paquetes devueltos', 'Kolis retounen'),
    'transit_hours_sum': ('Heures de transit (somme)', 'Transit hours (total)', 'Horas de tránsito (suma)', 'Èdtan transpò (total)'), 'transit_count': ('Colis au délai mesuré', 'Parcels with measured transit', 'Paquetes con tránsito medido', 'Kolis ki gen tan mezire'),
    'shipments_dispatched': ('Expéditions parties', 'Shipments dispatched', 'Envíos despachados', 'Ekspedisyon ki pati'), 'shipments_arrived': ('Expéditions arrivées', 'Shipments arrived', 'Envíos llegados', 'Ekspedisyon ki rive'),
    'tasks_completed': ('Missions terminées', 'Tasks completed', 'Misiones completadas', 'Misyon fini'), 'tasks_failed': ('Missions échouées', 'Tasks failed', 'Misiones fallidas', 'Misyon ki echwe'),
    'scans_total': ('Scans', 'Scans', 'Escaneos', 'Eskanè'), 'scans_rejected': ('Scans refusés (nombre)', 'Rejected scans (count)', 'Escaneos rechazados (cantidad)', 'Eskanè refize (kantite)'),
    'incidents_opened': ('Incidents signalés', 'Issues reported', 'Incidencias reportadas', 'Pwoblèm siyale'), 'tickets_opened': ('Tickets de support ouverts', 'Support tickets opened', 'Tickets de soporte abiertos', 'Tikè sipò ouvè'),
    'customers_new': ('Nouveaux clients', 'New customers', 'Clientes nuevos', 'Nouvo kliyan'), 'revenue_net_usd': ('Revenus (hors taxe)', 'Revenue (before tax)', 'Ingresos (sin impuestos)', 'Revni (san taks)'),
    'revenue_tax_usd': ('Taxes facturées', 'Taxes billed', 'Impuestos facturados', 'Taks faktire'), 'payments_usd': ('Paiements reçus', 'Payments received', 'Pagos recibidos', 'Peman resevwa'),
    'payments_count': ('Nombre de paiements', 'Number of payments', 'Número de pagos', 'Kantite peman'), 'refunds_usd': ('Remboursements', 'Refunds', 'Reembolsos', 'Ranbousman')})
# La santé du système (assets/js/ses-sante.js, phase 17)
a(('c-sa-intro', "Ce que la base sait d'elle-même : files d'attente, échecs, sauvegardes et leur vérification, fraîcheur des rapports, erreurs remontées par les navigateurs. Chaque contrôle a ses seuils ; le verdict est celui de la base.",
   'What the database knows about itself: queues, failures, backups and their verification, report freshness, errors reported by browsers. Each check has its thresholds; the verdict is the database\'s.',
   'Lo que la base de datos sabe de sí misma: colas, fallos, copias de seguridad y su verificación, frescura de los informes, errores enviados por los navegadores. Cada control tiene sus umbrales; el veredicto es el de la base.',
   'Sa baz done a konnen sou tèt li : fil datant, echèk, sovgad ak verifikasyon yo, fraîcheur rapò yo, erè navigatè yo voye. Chak kontwòl gen limit li ; se baz la ki bay desizyon an.'),
  ('c-sa-general', 'État général : {etat}', 'Overall status: {etat}', 'Estado general: {etat}', 'Eta jeneral : {etat}'),
  ('c-sa-genere', 'Relevé le {date} · niveau de migration {niveau}', 'Checked on {date} · migration level {niveau}', 'Revisado el {date} · nivel de migración {niveau}', 'Tcheke le {date} · nivo migrasyon {niveau}'),
  ('c-sa-controles', 'Contrôles', 'Checks', 'Controles', 'Kontwòl'),
  ('c-sa-battements', 'Travaux planifiés (dernier signal)', 'Scheduled jobs (last signal)', 'Tareas programadas (última señal)', 'Travay planifye (dènye siyal)'),
  ('c-sa-erreurs', 'Dernières erreurs des navigateurs', 'Latest browser errors', 'Últimos errores de los navegadores', 'Dènye erè navigatè yo'),
  ('c-sa-aucun-battement', "Aucun travail planifié n'a encore donné signe de vie.", 'No scheduled job has reported yet.', 'Ninguna tarea programada ha dado señales todavía.', 'Okenn travay planifye poko bay siyal.'),
  ('c-sa-aucune-erreur', 'Aucune erreur remontée.', 'No error reported.', 'Ningún error reportado.', 'Pa gen okenn erè ki rive.'),
  ('c-sa-jamais', 'jamais', 'never', 'nunca', 'janm'),
  ('c-sa-seuils', 'alerte ≥ {alerte} · échec ≥ {echec}', 'warning ≥ {alerte} · failure ≥ {echec}', 'alerta ≥ {alerte} · fallo ≥ {echec}', 'alèt ≥ {alerte} · echèk ≥ {echec}'),
  ('c-sa-col-controle', 'Contrôle', 'Check', 'Control', 'Kontwòl'),
  ('c-sa-col-etat', 'État', 'Status', 'Estado', 'Eta'),
  ('c-sa-col-valeur', 'Valeur', 'Value', 'Valor', 'Valè'),
  ('c-sa-col-seuils', 'Seuils', 'Thresholds', 'Umbrales', 'Limit'),
  ('c-sa-col-quand', 'Quand', 'When', 'Cuándo', 'Kilè'),
  ('c-sa-col-page', 'Page', 'Page', 'Página', 'Paj'),
  ('c-sa-col-message', 'Message', 'Message', 'Mensaje', 'Mesaj'),
  ('c-sa-col-ref', 'Référence', 'Reference', 'Referencia', 'Referans'))
famille('c-sa-s-', {'OK': ('OK', 'OK', 'OK', 'OK'), 'WARN': ('Alerte', 'Warning', 'Alerta', 'Alèt'), 'FAIL': ('En échec', 'Failing', 'En fallo', 'An echèk')})
famille('c-sa-u-', {'minutes': ('min', 'min', 'min', 'min'), 'hours': ('h', 'h', 'h', 'è'), 'days': ('j', 'd', 'd', 'j'), 'MB': ('Mo', 'MB', 'MB', 'Mo')})
famille('c-sa-h-', {'backup': ('Sauvegarde', 'Backup', 'Copia de seguridad', 'Sovgad'), 'restore_check': ('Vérification par restauration', 'Restore check', 'Verificación por restauración', 'Verifikasyon pa restorasyon'),
                    'notifications_worker': ('Envoi des notifications', 'Notification sending', 'Envío de notificaciones', 'Voye notifikasyon'), 'analytics_refresh': ('Calcul des rapports', 'Report computation', 'Cálculo de informes', 'Kalkil rapò'),
                    'deploy': ('Mise en ligne', 'Deployment', 'Despliegue', 'Mete sou entènèt')})
famille('c-sa-c-', {
    'events_pending': ('Événements en attente', 'Pending events', 'Eventos pendientes', 'Evènman an atant'), 'events_oldest_minutes': ('Plus vieil événement en attente', 'Oldest pending event', 'Evento pendiente más antiguo', 'Pi vye evènman an atant'),
    'dead_letters_open': ('Échecs définitifs non résolus', 'Unresolved permanent failures', 'Fallos definitivos sin resolver', 'Echèk definitif ki pa rezoud'),
    'notifications_failed_24h': ('Notifications en échec (24 h)', 'Failed notifications (24 h)', 'Notificaciones fallidas (24 h)', 'Notifikasyon ki echwe (24 è)'),
    'notifications_oldest_due_minutes': ('Plus vieille notification à envoyer', 'Oldest notification due', 'Notificación pendiente más antigua', 'Pi vye notifikasyon pou voye'),
    'backup_age_hours': ('Dernière sauvegarde réussie', 'Last successful backup', 'Última copia de seguridad correcta', 'Dènye sovgad ki reyisi'),
    'restore_check_age_days': ('Dernière restauration vérifiée', 'Last verified restore', 'Última restauración verificada', 'Dènye restorasyon verifye'),
    'jobs_failed_24h': ('Travaux en échec (24 h)', 'Failed jobs (24 h)', 'Tareas fallidas (24 h)', 'Travay ki echwe (24 è)'),
    'analytics_age_hours': ('Dernier calcul des rapports', 'Last report computation', 'Último cálculo de informes', 'Dènye kalkil rapò'),
    'analytics_missing_days_7': ('Jours sans rapport (7 derniers)', 'Days without report (last 7)', 'Días sin informe (últimos 7)', 'Jou san rapò (7 dènye)'),
    'audit_entries_24h': ("Entrées du journal d'audit (24 h)", 'Audit log entries (24 h)', 'Entradas del registro de auditoría (24 h)', 'Antre jounal odit (24 è)'),
    'client_errors_24h': ('Erreurs des navigateurs (24 h)', 'Browser errors (24 h)', 'Errores de navegadores (24 h)', 'Erè navigatè (24 è)'),
    'rate_limited_windows_24h': ('Comptes ayant atteint un plafond (24 h)', 'Accounts that hit a limit (24 h)', 'Cuentas que alcanzaron un límite (24 h)', 'Kont ki rive nan yon limit (24 è)'),
    'database_size_mb': ('Taille de la base', 'Database size', 'Tamaño de la base de datos', 'Gwosè baz done a'), 'schema_level': ('Niveau de migration', 'Migration level', 'Nivel de migración', 'Nivo migrasyon')})
famille('c-scan-', {
    'ACCEPTED': ('Accepté', 'Accepted', 'Aceptado', 'Aksepte'), 'UNKNOWN_PARCEL': ('Colis inconnu', 'Unknown parcel', 'Paquete desconocido', 'Kolis enkoni'), 'INVALID_CODE': ('Code invalide', 'Invalid code', 'Código inválido', 'Kòd pa valab'),
    'DUPLICATE': ('Doublon', 'Duplicate', 'Duplicado', 'Doub'), 'WRONG_WAREHOUSE': ('Mauvais entrepôt', 'Wrong warehouse', 'Almacén equivocado', 'Move depo'), 'ALREADY_DISPATCHED': ('Déjà expédié', 'Already dispatched', 'Ya despachado', 'Deja ekspedye'),
    'DAMAGED': ('Endommagé', 'Damaged', 'Dañado', 'Domaje'), 'PROHIBITED': ('Interdit', 'Prohibited', 'Prohibido', 'Entèdi'), 'NO_CUSTOMER': ('Sans client', 'No customer', 'Sin cliente', 'San kliyan'), 'WRONG_STATE': ('Mauvais état', 'Wrong state', 'Estado incorrecto', 'Move eta')})
famille('c-but-', {'receive': ('Réception', 'Receiving', 'Recepción', 'Resepsyon'), 'verify': ('Vérification', 'Checking', 'Verificación', 'Verifikasyon'), 'store': ('Rangement', 'Storing', 'Almacenamiento', 'Ranjman'),
                   'move': ('Déplacement', 'Moving', 'Traslado', 'Deplasman'), 'consolidate': ('Consolidation', 'Consolidation', 'Consolidación', 'Gwoupman kolis'), 'dispatch': ('Départ en expédition', 'Dispatch', 'Despacho', 'Ekspedisyon'),
                   'lookup': ('Consultation', 'Lookup', 'Consulta', 'Konsiltasyon')})
famille('c-bk-', {'office': ('Bureau', 'Office', 'Oficina', 'Biwo'), 'hub': ('Hub', 'Hub', 'Hub', 'Hub'), 'agency': ('Agence', 'Agency', 'Agencia', 'Ajans'), 'warehouse_site': ('Site d\'entrepôt', 'Warehouse site', 'Sitio de almacén', 'Sit depo')})
famille('c-etat-', {'UNKNOWN': ('Non contrôlé', 'Not inspected', 'Sin inspeccionar', 'Pa kontwole'), 'GOOD': ('Bon état', 'Good condition', 'Buen estado', 'Bon kondisyon'),
                    'MINOR_DAMAGE': ('Légèrement abîmé', 'Slightly damaged', 'Ligeramente dañado', 'Ti kras domaje'), 'DAMAGED': ('Endommagé', 'Damaged', 'Dañado', 'Domaje')})
famille('c-aut-', {'core': ('Le noyau logistique', 'The logistics core', 'El núcleo logístico', 'Nwayo lojistik la'), 'legacy': ("L'ancien système", 'The previous system', 'El sistema anterior', 'Ansyen sistèm lan')})

# ---------------------------------------------------------------------------------------------------------------------------------------------------------
BRACES = re.compile(r'\{[a-z_]+\}')


def verifier():
    par_fr = {}
    cles = set()
    for cle, fr, en, es, ht in T:
        assert cle not in cles, 'clé en double : ' + cle
        cles.add(cle)
        for langue, texte in (('fr', fr), ('en', en), ('es', es), ('ht', ht)):
            assert texte.strip(), '%s : texte %s vide' % (cle, langue)
            assert '’' not in texte and '‘' not in texte, '%s : apostrophe typographique (%s)' % (cle, langue)
            assert '<' not in texte and '>' not in texte, '%s : chevron dans le texte' % cle
            assert BRACES.findall(texte) == BRACES.findall(fr), '%s : les variables {…} ne se retrouvent pas en %s' % (cle, langue)
        if fr in par_fr:
            assert par_fr[fr][1:] == (en, es, ht), 'le français « %s » a deux traductions différentes (%s et %s)' % (fr, par_fr[fr][0], cle)
        else:
            par_fr[fr] = (cle, en, es, ht)
    return par_fr


def echappe_html(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def main():
    par_fr = verifier()
    # 1. le gabarit
    g = GABARIT.read_text(encoding='utf-8')
    bloc = D1 + '\n' + '\n'.join('  <span data-t="%s">%s</span>' % (cle, echappe_html(fr)) for cle, fr, _, _, _ in T) + '\n  ' + F1
    if D1 in g:
        g = re.sub(re.escape(D1) + r'.*?' + re.escape(F1), lambda m: bloc, g, flags=re.S)
    else:
        assert g.count('</template>') == 1, 'un seul <template> attendu dans le gabarit'
        g = g.replace('</template>', '  ' + bloc + '\n</template>')
    GABARIT.write_text(g, encoding='utf-8')
    # 2. le dictionnaire : seulement ce qui n'existe pas déjà (ailleurs que dans le bloc géré)
    d = DICO.read_text(encoding='utf-8')
    hors = re.sub(re.escape(D2) + r'.*?' + re.escape(F2), '', d, flags=re.S)
    existant = {}
    for fichier in (hors, DICO_COMMUN.read_text(encoding='utf-8')):
        for m in re.finditer(r'^\s*"((?:[^"\\]|\\.)*)"\s*:\s*\[\s*"((?:[^"\\]|\\.)*)"\s*,\s*"((?:[^"\\]|\\.)*)"\s*,\s*"((?:[^"\\]|\\.)*)"\s*\]', fichier, flags=re.M):
            existant[json.loads('"%s"' % m.group(1))] = tuple(json.loads('"%s"' % m.group(i)) for i in (2, 3, 4))
    lignes, autres = [], []
    for fr, (cle, en, es, ht) in sorted(par_fr.items(), key=lambda x: x[0]):
        if fr in existant:
            if existant[fr] != (en, es, ht):
                autres.append(fr)
            continue
        lignes.append('  %s: [%s, %s, %s],' % (json.dumps(fr, ensure_ascii=False), json.dumps(en, ensure_ascii=False), json.dumps(es, ensure_ascii=False), json.dumps(ht, ensure_ascii=False)))
    bloc2 = D2 + '\n' + '\n'.join(lignes) + '\n' + F2
    if D2 in d:
        d = re.sub(re.escape(D2) + r'.*?' + re.escape(F2), lambda m: bloc2, d, flags=re.S)
    else:
        i = d.rindex('\n});')
        d = d[:i].rstrip().rstrip(',') + ',\n\n' + bloc2 + d[i:]
    DICO.write_text(d, encoding='utf-8')
    print('centre : %d textes, %d entrées de dictionnaire (%d déjà connues, dont %d avec une formulation différente : celle du dictionnaire fait foi)' % (len(T), len(lignes), len(par_fr) - len(lignes), len(autres)))
    if '--detail' in sys.argv:
        print('\n'.join('  ' + x for x in autres))


if __name__ == '__main__':
    main()
