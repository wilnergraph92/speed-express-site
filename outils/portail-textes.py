#!/usr/bin/env python3
"""Les textes du portail client : UNE table (français, anglais, espagnol, créole), deux sorties.

    python3 outils/portail-textes.py

Elle écrit, entre des repères, (1) les <span data-t="…"> du gabarit de la page (outils/espace/espace-client.html) et (2) les entrées du
dictionnaire (assets/js/lang-dict-11.js). Relancée, elle ne change rien si la table n'a pas changé. Ajouter un texte au portail, c'est
ajouter UNE ligne ici, puis relancer ce script et `python3 outils/mise-en-page.py`.

Elle refuse : deux clés avec le même français mais des traductions différentes (le dictionnaire est indexé par le texte français), un texte vide,
une apostrophe typographique (le moteur de traduction ne la reconnaît pas), des accolades qui ne se retrouvent pas d'une langue à l'autre,
et une entrée qui existe déjà dans le dictionnaire avec une AUTRE traduction.
"""
import json
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
GABARIT = SITE / 'outils/espace/espace-client.html'
DICO = SITE / 'assets/js/lang-dict-11.js'
DICO_COMMUN = SITE / 'assets/js/lang-dict.js'
D1, F1 = '<!-- portail:debut -->', '<!-- portail:fin -->'
D2, F2 = '  // --- portail:debut ---', '  // --- portail:fin ---'

# (clé, français, anglais, espagnol, créole)
T = []


def a(*lignes):
    T.extend(lignes)


# ---- navigation et états ------------------------------------------------------------------------------------------------------
a(('p-colis', 'Colis', 'Parcel', 'Paquete', 'Kolis'),
  ('p-nav-titre', "Sections de l'espace client", 'Customer area sections', 'Secciones del área de cliente', 'Seksyon espas kliyan an'),
  ('p-nav-tableau', 'Tableau de bord', 'Dashboard', 'Panel de control', 'Tablo kontwòl'),
  ('p-nav-colis', 'Mes colis', 'My parcels', 'Mis paquetes', 'Kolis mwen yo'),
  ('p-nav-expeditions', 'Mes expéditions', 'My shipments', 'Mis envíos', 'Ekspedisyon mwen yo'),
  ('p-nav-suivi', 'Suivi', 'Tracking', 'Seguimiento', 'Swivi'),
  ('p-nav-consolidations', 'Consolidations', 'Consolidations', 'Consolidaciones', 'Gwoupman kolis'),
  ('p-nav-factures', 'Factures', 'Invoices', 'Facturas', 'Fakti'),
  ('p-nav-paiements', 'Paiements', 'Payments', 'Pagos', 'Peman'),
  ('p-nav-documents', 'Documents', 'Documents', 'Documentos', 'Dokiman'),
  ('p-nav-adresses', 'Adresses', 'Addresses', 'Direcciones', 'Adrès'),
  ('p-nav-enlevements', 'Enlèvement', 'Pickup', 'Recogida', 'Ranmasaj'),
  ('p-nav-livraisons', 'Livraison', 'Delivery', 'Entrega', 'Livrezon'),
  ('p-nav-notifications', 'Notifications', 'Notifications', 'Notificaciones', 'Notifikasyon'),
  ('p-nav-support', 'Support', 'Support', 'Soporte', 'Sipò'),
  ('p-nav-profil', 'Profil', 'Profile', 'Perfil', 'Pwofil'),
  ('p-nav-non-lues', '{nombre} non lue(s)', '{nombre} unread', '{nombre} sin leer', '{nombre} pa li'),
  ('p-nav-ouverts', '{nombre} ouvert(s)', '{nombre} open', '{nombre} abierto(s)', '{nombre} ouvè'),
  ('p-chargement', 'Chargement…', 'Loading…', 'Cargando…', 'Chajman…'),
  ('p-attente', 'Envoi en cours…', 'Sending…', 'Enviando…', 'Y ap voye…'),
  ('p-reessayer', 'Réessayer', 'Try again', 'Reintentar', 'Eseye ankò'),
  ('p-enregistrer', 'Enregistrer', 'Save', 'Guardar', 'Anrejistre'),
  ('p-annuler', 'Annuler', 'Cancel', 'Cancelar', 'Anile'),
  ('p-modifier', 'Modifier', 'Edit', 'Modificar', 'Modifye'),
  ('p-supprimer', 'Supprimer', 'Delete', 'Eliminar', 'Efase'),
  ('p-afficher-plus', 'Afficher plus', 'Show more', 'Mostrar más', 'Montre plis'),
  ('p-colis-n', '{nombre} colis', '{nombre} parcel(s)', '{nombre} paquete(s)', '{nombre} kolis'),
  ('p-colis-affiches', '{nombre} colis affichés sur {total}', 'Showing {nombre} of {total} parcels', 'Mostrando {nombre} de {total} paquetes', 'Y ap montre {nombre} sou {total} kolis'),
  ('p-frise', 'Étapes du parcours du colis', 'Parcel journey steps', 'Etapas del recorrido del paquete', 'Etap vwayaj kolis la'),
  ('p-etape-actuelle', 'étape actuelle', 'current step', 'etapa actual', 'etap kounye a'),
  ('p-dernier-etat', 'Dernier état', 'Latest status', 'Último estado', 'Dènye eta'),
  ('p-suivi-titre', 'Suivi daté du colis', 'Dated tracking of the parcel', 'Seguimiento fechado del paquete', 'Swivi kolis la ak dat'),
  ('p-suivi-vide', "Aucun événement enregistré pour l'instant.", 'No event recorded yet.', 'Aún no hay eventos registrados.', 'Pa gen okenn evènman anrejistre pou kounye a.'))

# ---- les étapes que la base calcule ---------------------------------------------------------------------------------------------
a(('stage-registered', 'Enregistré', 'Registered', 'Registrado', 'Anrejistre'),
  ('stage-received', "Reçu à l'entrepôt", 'Received at the warehouse', 'Recibido en el almacén', 'Resevwa nan depo a'),
  ('stage-in_transit', 'En transit', 'In transit', 'En tránsito', 'An tranzit'),
  ('stage-customs', 'Arrivé · douane', 'Arrived · customs', 'Llegado · aduana', 'Rive · dwàn'),
  ('stage-at_hub', 'Disponible au hub', 'Available at the hub', 'Disponible en el hub', 'Disponib nan hub la'),
  ('stage-out_for_delivery', 'En livraison', 'Out for delivery', 'En reparto', 'Nan livrezon'),
  ('stage-delivered', 'Livré', 'Delivered', 'Entregado', 'Livre'),
  ('stage-on_hold', 'En attente', 'On hold', 'En espera', 'An datant'),
  ('stage-incident', 'Incident signalé', 'Issue reported', 'Incidencia señalada', 'Pwoblèm siyale'),
  ('stage-lost', 'Perdu', 'Lost', 'Perdido', 'Pèdi'),
  ('stage-cancelled', 'Annulé', 'Cancelled', 'Cancelado', 'Anile'),
  ('stage-returned', 'Retourné', 'Returned', 'Devuelto', 'Retounen'),
  ('stage-preparing', 'En préparation', 'Being prepared', 'En preparación', 'Y ap prepare'),
  ('stage-closed', 'Terminée', 'Completed', 'Finalizada', 'Fini'),
  ('p-arret-on_hold', "Votre colis est en attente. Notre équipe vous contactera si une action est nécessaire.", 'Your parcel is on hold. Our team will contact you if any action is needed.',
   'Su paquete está en espera. Nuestro equipo le contactará si es necesaria alguna acción.', 'Kolis ou a an datant. Ekip nou an ap kontakte w si gen yon aksyon pou fè.'),
  ('p-arret-incident', "Un incident a été signalé sur ce colis. Notre équipe s'en occupe.", 'An issue was reported on this parcel. Our team is handling it.',
   'Se ha señalado una incidencia en este paquete. Nuestro equipo se encarga.', 'Yon pwoblèm siyale sou kolis sa a. Ekip nou an ap okipe l.'),
  ('p-arret-lost', 'Ce colis est déclaré perdu. Contactez le support.', 'This parcel is declared lost. Please contact support.', 'Este paquete se declara perdido. Contacte con soporte.',
   'Kolis sa a deklare pèdi. Kontakte sipò a.'),
  ('p-arret-cancelled', 'Ce colis a été annulé.', 'This parcel was cancelled.', 'Este paquete fue cancelado.', 'Kolis sa a anile.'),
  ('p-arret-returned', "Ce colis a été retourné à l'expéditeur.", 'This parcel was returned to the sender.', 'Este paquete fue devuelto al remitente.', 'Kolis sa a retounen bay moun ki voye l la.'),
  ('req-requested', 'Demandée', 'Requested', 'Solicitada', 'Mande'),
  ('req-scheduled', 'Planifiée', 'Scheduled', 'Programada', 'Planifye'),
  ('req-on_the_way', 'En route', 'On the way', 'En camino', 'Sou wout'),
  ('req-completed', 'Terminée', 'Completed', 'Finalizada', 'Fini'),
  ('req-missed', 'Manquée', 'Missed', 'Fallida', 'Rate'),
  ('req-rejected', 'Refusée', 'Declined', 'Rechazada', 'Refize'),
  ('req-cancelled', 'Annulée', 'Cancelled', 'Anulada', 'Anile'),
  ('req-delivered', 'Livrée', 'Delivered', 'Entregada', 'Livre'))

# ---- le suivi : événements du journal ----------------------------------------------------------------------------------------------
a(('evt-ParcelCreated', 'Colis enregistré', 'Parcel registered', 'Paquete registrado', 'Kolis anrejistre'),
  ('evt-ParcelReceived', "Reçu à l'entrepôt", 'Received at the warehouse', 'Recibido en el almacén', 'Resevwa nan depo a'),
  ('evt-ParcelVerified', "Vérifié à l'entrepôt", 'Checked at the warehouse', 'Verificado en el almacén', 'Verifye nan depo a'),
  ('evt-ParcelConsolidated', "Regroupé pour l'expédition", 'Grouped for shipping', 'Agrupado para el envío', 'Gwoupe pou ekspedisyon an'),
  ('evt-ParcelReadyForExport', 'Prêt à partir', 'Ready to depart', 'Listo para salir', 'Pare pou pati'),
  ('evt-ParcelInTransit', 'En transit', 'In transit', 'En tránsito', 'An tranzit'),
  ('evt-ParcelArrived', 'Arrivé à destination', 'Arrived at destination', 'Llegado a destino', 'Rive nan destinasyon'),
  ('evt-CustomsStarted', 'Dédouanement en cours', 'Customs clearance in progress', 'Despacho de aduana en curso', 'Dedwanman ap fèt'),
  ('evt-CustomsCleared', 'Dédouané', 'Cleared customs', 'Despachado en aduana', 'Pase dwàn'),
  ('evt-ParcelAtDestinationHub', 'Arrivé au hub', 'Arrived at the hub', 'Llegado al hub', 'Rive nan hub la'),
  ('evt-DeliveryAssigned', 'Livraison planifiée', 'Delivery scheduled', 'Entrega programada', 'Livrezon planifye'),
  ('evt-OutForDelivery', 'En cours de livraison', 'Out for delivery', 'En reparto', 'Y ap livre'),
  ('evt-Delivered', 'Livré', 'Delivered', 'Entregado', 'Livre'),
  ('evt-ParcelOnHold', 'Mis en attente', 'Put on hold', 'Puesto en espera', 'Mete an datant'),
  ('evt-ParcelResumed', 'Traitement repris', 'Processing resumed', 'Tratamiento reanudado', 'Tretman repran'),
  ('evt-ParcelCancelled', 'Annulé', 'Cancelled', 'Cancelado', 'Anile'),
  ('evt-ParcelDamaged', 'Incident signalé', 'Issue reported', 'Incidencia señalada', 'Pwoblèm siyale'),
  ('evt-ParcelLost', 'Déclaré perdu', 'Declared lost', 'Declarado perdido', 'Deklare pèdi'),
  ('evt-ParcelReturned', "Retourné à l'expéditeur", 'Returned to the sender', 'Devuelto al remitente', 'Retounen bay moun ki voye l la'),
  ('evt-ParcelReturnedToHub', 'Livraison manquée : retour au hub', 'Delivery missed: back at the hub', 'Entrega fallida: de vuelta en el hub', 'Livrezon rate: retounen nan hub la'),
  ('mode-air', 'Aérien', 'Air', 'Aéreo', 'Avyon'),
  ('mode-sea', 'Maritime', 'Sea', 'Marítimo', 'Bato'),
  ('mode-ground', 'Terrestre', 'Ground', 'Terrestre', 'Teren'),
  ('customs-processing', 'Dédouanement en cours', 'Customs clearance in progress', 'Despacho de aduana en curso', 'Dedwanman ap fèt'),
  ('customs-cleared', 'Dédouané', 'Cleared customs', 'Despachado en aduana', 'Pase dwàn'),
  ('customs-rejected', 'Dédouanement refusé', 'Customs clearance refused', 'Despacho de aduana rechazado', 'Dedwanman refize'),
  ('cons-OPEN', 'Regroupement en cours', 'Being grouped', 'Agrupación en curso', 'Gwoupman ap fèt'),
  ('cons-CLOSED', 'Regroupement terminé', 'Grouping complete', 'Agrupación terminada', 'Gwoupman fini'),
  ('cons-SHIPPED', 'Expédié', 'Shipped', 'Enviado', 'Voye'),
  ('cons-CANCELLED', 'Annulé', 'Cancelled', 'Cancelado', 'Anile'),
  ('incident-CUSTOMER_ABSENT', 'Client absent', 'Customer absent', 'Cliente ausente', 'Kliyan an pa t la'),
  ('incident-WRONG_ADDRESS', 'Adresse incorrecte', 'Wrong address', 'Dirección incorrecta', 'Move adrès'),
  ('incident-DAMAGED', 'Colis endommagé', 'Parcel damaged', 'Paquete dañado', 'Kolis domaje'),
  ('incident-REFUSED', 'Colis refusé', 'Parcel refused', 'Paquete rechazado', 'Kolis refize'),
  ('incident-VEHICLE_PROBLEM', 'Problème de véhicule', 'Vehicle problem', 'Problema con el vehículo', 'Pwoblèm ak veyikil la'),
  ('incident-PAYMENT_PROBLEM', 'Problème de paiement', 'Payment problem', 'Problema de pago', 'Pwoblèm peman'),
  ('incident-OTHER', 'Autre raison', 'Other reason', 'Otro motivo', 'Lòt rezon'))

# ---- tableau de bord ---------------------------------------------------------------------------------------------------------------
a(('p-tb-impayees', 'Factures à régler', 'Invoices to pay', 'Facturas por pagar', 'Fakti pou peye'),
  ('p-tb-enlevements', 'Enlèvements en cours', 'Pickups in progress', 'Recogidas en curso', 'Ranmasaj ki ap fèt'),
  ('p-tb-non-lues', 'Notifications non lues', 'Unread notifications', 'Notificaciones sin leer', 'Notifikasyon ki pa li'),
  ('p-tb-tickets', 'Demandes de support ouvertes', 'Open support requests', 'Solicitudes de soporte abiertas', 'Demand sipò ki ouvè'),
  ('p-tb-prochaines', 'Prochaines livraisons', 'Upcoming deliveries', 'Próximas entregas', 'Pwochen livrezon'),
  ('p-tb-aucune-livraison', 'Aucune livraison prévue.', 'No delivery scheduled.', 'No hay entregas programadas.', 'Pa gen livrezon planifye.'),
  ('p-tb-derniers', 'Derniers événements', 'Latest events', 'Últimos eventos', 'Dènye evènman yo'),
  ('p-tb-aucun-evenement', 'Aucun événement pour le moment.', 'No events yet.', 'Aún no hay eventos.', 'Pa gen evènman pou kounye a.'),
  ('p-tb-actions', 'Actions rapides', 'Quick actions', 'Acciones rápidas', 'Aksyon rapid'),
  ('p-tb-demander-enlevement', 'Demander un enlèvement', 'Request a pickup', 'Solicitar una recogida', 'Mande yon ranmasaj'),
  ('p-tb-demander-livraison', 'Demander une livraison', 'Request a delivery', 'Solicitar una entrega', 'Mande yon livrezon'),
  ('p-tb-suivre', 'Suivre un colis', 'Track a parcel', 'Seguir un paquete', 'Swiv yon kolis'),
  ('p-tb-support', 'Écrire au support', 'Contact support', 'Escribir a soporte', 'Ekri sipò a'))

# ---- mes colis, suivi, expéditions, consolidations ----------------------------------------------------------------------------------------
a(('p-chercher-colis', 'Chercher un numéro, un contenu ou un destinataire', 'Search a number, contents or recipient', 'Buscar un número, contenido o destinatario', 'Chèche yon nimewo, yon kontni oswa yon destinatè'),
  ('p-chercher-colis-libelle', 'Chercher dans mes colis', 'Search my parcels', 'Buscar en mis paquetes', 'Chèche nan kolis mwen yo'),
  ('p-filtrer-etape', 'Filtrer par étape', 'Filter by step', 'Filtrar por etapa', 'Filtre pa etap'),
  ('p-voir-suivi', 'Voir le suivi', 'View tracking', 'Ver el seguimiento', 'Wè swivi a'),
  ('p-retour-colis', 'Retour à mes colis', 'Back to my parcels', 'Volver a mis paquetes', 'Tounen nan kolis mwen yo'),
  ('p-d-actuellement', 'Actuellement :', 'Currently:', 'Actualmente:', 'Kounye a :'),
  ('p-d-suivi', 'Suivi du colis', 'Parcel tracking', 'Seguimiento del paquete', 'Swivi kolis la'),
  ('p-d-infos', 'Informations', 'Details', 'Información', 'Enfòmasyon'),
  ('p-d-destinataire', 'Destinataire', 'Recipient', 'Destinatario', 'Destinatè'),
  ('p-d-valeur', 'Valeur déclarée', 'Declared value', 'Valor declarado', 'Valè deklare'),
  ('p-d-expedition', 'Expédition', 'Shipment', 'Envío', 'Ekspedisyon'),
  ('p-d-code', 'Code', 'Code', 'Código', 'Kòd'),
  ('p-d-service', 'Service', 'Service', 'Servicio', 'Sèvis'),
  ('p-d-trajet', 'Trajet', 'Route', 'Trayecto', 'Wout'),
  ('p-d-transporteur', 'Transporteur', 'Carrier', 'Transportista', 'Transpòtè'),
  ('p-d-depart', 'Départ', 'Departure', 'Salida', 'Depa'),
  ('p-d-arrivee-prevue', 'Arrivée prévue', 'Expected arrival', 'Llegada prevista', 'Rive prevwa'),
  ('p-d-arrivee', 'Arrivée', 'Arrival', 'Llegada', 'Rive'),
  ('p-d-douane', 'Douane', 'Customs', 'Aduana', 'Dwàn'),
  ('p-d-livraison', 'Livraison', 'Delivery', 'Entrega', 'Livrezon'),
  ('p-d-date-prevue', 'Date prévue', 'Planned date', 'Fecha prevista', 'Dat prevwa'),
  ('p-d-fenetre', 'Créneau', 'Time slot', 'Franja horaria', 'Kreno'),
  ('p-d-code-livraison', 'Code de livraison', 'Delivery code', 'Código de entrega', 'Kòd livrezon'),
  ('p-d-code-envoye', 'Envoyé : voir vos notifications', 'Sent: see your notifications', 'Enviado: vea sus notificaciones', 'Voye : gade notifikasyon ou yo'),
  ('p-d-code-exige', 'Un code vous sera envoyé avant la remise', 'A code will be sent to you before handover', 'Se le enviará un código antes de la entrega', 'Y ap voye yon kòd ba ou anvan livrezon an'),
  ('p-d-incident', 'Incident', 'Issue', 'Incidencia', 'Pwoblèm'),
  ('p-d-recu-par', 'Reçu par', 'Received by', 'Recibido por', 'Resevwa pa'),
  ('p-d-recu-le', 'Remis le', 'Handed over on', 'Entregado el', 'Livre le'),
  ('p-d-consolidation', 'Consolidation', 'Consolidation', 'Consolidación', 'Gwoupman kolis'),
  ('p-d-etat', 'État', 'Status', 'Estado', 'Eta'),
  ('p-d-factures', 'Factures', 'Invoices', 'Facturas', 'Fakti'),
  ('p-d-ecrire-support', 'Une question sur ce colis ?', 'A question about this parcel?', '¿Una pregunta sobre este paquete?', 'Yon kesyon sou kolis sa a ?'),
  ('p-suivi-intro', "Entrez le numéro d'un de vos colis pour voir où il en est.", 'Enter the number of one of your parcels to see where it is.', 'Introduzca el número de uno de sus paquetes para ver dónde está.',
   'Antre nimewo youn nan kolis ou yo pou wè ki kote li ye.'),
  ('p-numero-colis', 'Numéro de colis', 'Parcel number', 'Número de paquete', 'Nimewo kolis'),
  ('p-numero-requis', 'Saisissez un numéro de colis.', 'Enter a parcel number.', 'Introduzca un número de paquete.', 'Antre yon nimewo kolis.'),
  ('p-suivre', 'Suivre', 'Track', 'Seguir', 'Swiv'),
  ('p-recents', 'Récents :', 'Recent:', 'Recientes:', 'Dènye yo :'),
  ('p-suivi-introuvable', 'Aucun de vos colis ne porte ce numéro. Vérifiez-le ou écrivez-nous.', 'None of your parcels has this number. Check it or write to us.',
   'Ninguno de sus paquetes tiene este número. Compruébelo o escríbanos.', 'Okenn nan kolis ou yo pa gen nimewo sa a. Verifye l oswa ekri nou.'),
  ('p-exp-intro', 'Les expéditions (vols, traversées) qui transportent vos colis.', 'The shipments (flights, crossings) carrying your parcels.', 'Los envíos (vuelos, travesías) que transportan sus paquetes.',
   'Ekspedisyon yo (vòl, travèse) ki pote kolis ou yo.'),
  ('p-exp-vide', 'Aucune expédition pour le moment : vos colis y apparaîtront dès leur départ.', 'No shipment yet: your parcels will appear here once they depart.',
   'Aún no hay envíos: sus paquetes aparecerán aquí en cuanto salgan.', 'Pa gen ekspedisyon pou kounye a : kolis ou yo ap parèt isit la le yo pati.'),
  ('p-exp-mes-colis', 'Vos colis dans cette expédition :', 'Your parcels in this shipment:', 'Sus paquetes en este envío:', 'Kolis ou yo nan ekspedisyon sa a :'),
  ('p-cons-intro', 'Vos colis regroupés avec d\'autres pour voyager ensemble.', 'Your parcels grouped with others to travel together.', 'Sus paquetes agrupados con otros para viajar juntos.',
   'Kolis ou yo ki gwoupe ak lòt pou vwayaje ansanm.'),
  ('p-cons-vide', 'Aucune consolidation pour le moment.', 'No consolidation yet.', 'Aún no hay consolidaciones.', 'Pa gen gwoupman pou kounye a.'),
  ('p-cons-ouverte', 'Ouverte le', 'Opened on', 'Abierta el', 'Louvri le'),
  ('p-cons-fermee', 'Fermée le', 'Closed on', 'Cerrada el', 'Fèmen le'),
  ('p-cons-expedition', 'Expédition', 'Shipment', 'Envío', 'Ekspedisyon'),
  ('p-cons-mes-colis', 'Vos colis', 'Your parcels', 'Sus paquetes', 'Kolis ou yo'))

# ---- factures, paiements, documents -------------------------------------------------------------------------------------------------------
a(('p-f-intro', 'Vos factures émises. Une facture émise ne change plus : pour toute question, écrivez au support.', 'Your issued invoices. An issued invoice never changes: for any question, contact support.',
   'Sus facturas emitidas. Una factura emitida ya no cambia: para cualquier duda, escriba a soporte.', 'Fakti ou yo ki emèt. Yon fakti ki emèt pa chanje ankò : pou nenpòt kesyon, ekri sipò a.'),
  ('p-f-solde-du', 'Solde à régler', 'Balance due', 'Saldo por pagar', 'Balans pou peye'),
  ('p-f-rien-du', 'Rien à régler', 'Nothing to pay', 'Nada que pagar', 'Anyen pou peye'),
  ('p-filtrer-factures', 'Filtrer les factures', 'Filter invoices', 'Filtrar facturas', 'Filtre fakti yo'),
  ('p-f-a-regler', 'À régler', 'To pay', 'Por pagar', 'Pou peye'),
  ('p-f-soldees', 'Soldées', 'Settled', 'Saldadas', 'Peye nèt'),
  ('p-f-emise', 'Émise le', 'Issued on', 'Emitida el', 'Emèt le'),
  ('p-f-echeance', 'Échéance', 'Due date', 'Vencimiento', 'Dat limit'),
  ('p-f-paye', 'Payé', 'Paid', 'Pagado', 'Peye'),
  ('p-f-reste', 'Reste à payer', 'Remaining', 'Pendiente', 'Rès pou peye'),
  ('p-f-voir', 'Voir', 'View', 'Ver', 'Gade'),
  ('p-f-retour', 'Retour aux factures', 'Back to invoices', 'Volver a las facturas', 'Tounen nan fakti yo'),
  ('p-f-lignes', 'Détail de la facture', 'Invoice details', 'Detalle de la factura', 'Detay fakti a'),
  ('p-f-description', 'Désignation', 'Description', 'Descripción', 'Deskripsyon'),
  ('p-f-resume', 'Résumé', 'Summary', 'Resumen', 'Rezime'),
  ('p-f-avoirs', 'Avoirs', 'Credit notes', 'Notas de crédito', 'Kredi'),
  ('p-f-rembourse', 'Remboursé', 'Refunded', 'Reembolsado', 'Rembouse'),
  ('p-f-question', 'Une question sur cette facture ?', 'A question about this invoice?', '¿Una pregunta sobre esta factura?', 'Yon kesyon sou fakti sa a ?'),
  ('p-f-comment-payer', 'Comment régler ?', 'How to pay?', '¿Cómo pagar?', 'Kijan pou peye ?'),
  ('p-f-payer-texte', 'Le paiement se fait en agence, par virement ou par mobile money. Écrivez-nous pour connaître les coordonnées et confirmer votre règlement.',
   'Payment is made at an agency, by bank transfer or by mobile money. Write to us for the details and to confirm your payment.',
   'El pago se realiza en una agencia, por transferencia o por mobile money. Escríbanos para conocer los datos y confirmar su pago.',
   'Peman an fèt nan ajans, pa transfè bank oswa pa mobile money. Ekri nou pou konnen koòdone yo epi konfime peman ou.'),
  ('p-f-payer-whatsapp', 'Écrire sur WhatsApp', 'Write on WhatsApp', 'Escribir por WhatsApp', 'Ekri sou WhatsApp'),
  ('p-f-introuvable', 'Cette facture est introuvable.', 'This invoice cannot be found.', 'Esta factura no se encuentra.', 'Pa jwenn fakti sa a.'),
  ('inv-ISSUED', 'Émise', 'Issued', 'Emitida', 'Emèt'),
  ('inv-PARTIALLY_PAID', 'Partiellement payée', 'Partially paid', 'Pagada parcialmente', 'Peye yon pati'),
  ('inv-PAID', 'Payée', 'Paid', 'Pagada', 'Peye'),
  ('inv-OVERDUE', 'En retard', 'Overdue', 'Vencida', 'An reta'),
  ('inv-CANCELLED', 'Annulée', 'Cancelled', 'Anulada', 'Anile'),
  ('inv-REFUNDED', 'Remboursée', 'Refunded', 'Reembolsada', 'Rembouse'),
  ('line-FREIGHT', 'Transport', 'Freight', 'Transporte', 'Transpò'),
  ('line-DISCOUNT', 'Remise', 'Discount', 'Descuento', 'Rabè'),
  ('line-SURCHARGE', 'Supplément', 'Surcharge', 'Suplemento', 'Sipleman'),
  ('line-SERVICE_FEE', 'Frais de service', 'Service fee', 'Gastos de servicio', 'Frè sèvis'),
  ('line-TAX', 'Taxe', 'Tax', 'Impuesto', 'Taks'),
  ('line-OTHER', 'Autre', 'Other', 'Otro', 'Lòt'),
  ('p-pay-intro', 'Les paiements reçus, les avoirs et les remboursements de vos factures.', 'The payments received, credit notes and refunds on your invoices.',
   'Los pagos recibidos, las notas de crédito y los reembolsos de sus facturas.', 'Peman yo resevwa, kredi yo ak ranbousman fakti ou yo.'),
  ('p-pay-recus', 'Paiements reçus', 'Payments received', 'Pagos recibidos', 'Peman resevwa'),
  ('p-pay-avoirs', 'Avoirs', 'Credit notes', 'Notas de crédito', 'Kredi'),
  ('p-pay-remboursements', 'Remboursements', 'Refunds', 'Reembolsos', 'Ranbousman'),
  ('p-pay-date', 'Date', 'Date', 'Fecha', 'Dat'),
  ('p-pay-numero', 'Numéro', 'Number', 'Número', 'Nimewo'),
  ('p-pay-facture', 'Facture', 'Invoice', 'Factura', 'Fakti'),
  ('p-pay-mode', 'Mode', 'Method', 'Método', 'Metòd'),
  ('p-pay-motif', 'Motif', 'Reason', 'Motivo', 'Rezon'),
  ('p-pay-remis', 'Remis : {montant}', 'Tendered: {montant}', 'Entregado: {montant}', 'Remèt : {montant}'),
  ('p-pay-aucun', 'Aucun pour le moment.', 'None yet.', 'Ninguno por ahora.', 'Okenn pou kounye a.'),
  ('method-CASH', 'Espèces', 'Cash', 'Efectivo', 'Lajan kach'),
  ('method-CARD', 'Carte', 'Card', 'Tarjeta', 'Kat'),
  ('method-TRANSFER', 'Virement', 'Bank transfer', 'Transferencia', 'Transfè bank'),
  ('method-MOBILE_MONEY', 'Mobile money', 'Mobile money', 'Mobile money', 'Mobile money'),
  ('method-CHECK', 'Chèque', 'Cheque', 'Cheque', 'Chèk'),
  ('method-OTHER', 'Autre', 'Other', 'Otro', 'Lòt'),
  ('p-doc-intro', 'Vos factures, avoirs, devis et reçus de livraison.', 'Your invoices, credit notes, quotes and delivery receipts.', 'Sus facturas, notas de crédito, presupuestos y recibos de entrega.',
   'Fakti ou yo, kredi, devi ak resi livrezon.'),
  ('p-doc-filtrer', 'Filtrer par type de document', 'Filter by document type', 'Filtrar por tipo de documento', 'Filtre pa kalite dokiman'),
  ('p-doc-vide', 'Aucun document pour le moment.', 'No document yet.', 'Aún no hay documentos.', 'Pa gen dokiman pou kounye a.'),
  ('p-doc-sur-facture', 'Sur la facture {numero}', 'On invoice {numero}', 'Sobre la factura {numero}', 'Sou fakti {numero}'),
  ('p-doc-lignes', 'Voir le détail', 'View details', 'Ver el detalle', 'Gade detay yo'),
  ('p-doc-valide', "valable jusqu'au {date}", 'valid until {date}', 'válido hasta el {date}', 'valab jiska {date}'),
  ('doc-INVOICE', 'Facture', 'Invoice', 'Factura', 'Fakti'),
  ('doc-CREDIT_NOTE', 'Avoir', 'Credit note', 'Nota de crédito', 'Kredi'),
  ('doc-QUOTE', 'Devis', 'Quote', 'Presupuesto', 'Devi'),
  ('doc-DELIVERY_RECEIPT', 'Reçu de livraison', 'Delivery receipt', 'Recibo de entrega', 'Resi livrezon'),
  ('quote-OFFERED', 'Proposé', 'Offered', 'Propuesto', 'Pwopoze'),
  ('quote-INVOICED', 'Facturé', 'Invoiced', 'Facturado', 'Fakti fèt'),
  ('quote-EXPIRED', 'Expiré', 'Expired', 'Vencido', 'Ekspire'))

# ---- adresses ----------------------------------------------------------------------------------------------------------------------------
a(('p-adr-intro', "Vos adresses de livraison et d'enlèvement. L'adresse par défaut est proposée en premier.", 'Your delivery and pickup addresses. The default address is offered first.',
   'Sus direcciones de entrega y recogida. La dirección predeterminada se ofrece primero.', 'Adrès livrezon ak ranmasaj ou yo. Adrès pa defo a parèt an premye.'),
  ('p-adr-ajouter', 'Ajouter une adresse', 'Add an address', 'Añadir una dirección', 'Ajoute yon adrès'),
  ('p-adr-vide', 'Aucune adresse enregistrée.', 'No saved address.', 'No hay direcciones guardadas.', 'Pa gen adrès anrejistre.'),
  ('p-adr-par-defaut', 'Par défaut', 'Default', 'Predeterminada', 'Pa defo'),
  ('p-adr-etiquette', "Nom de l'adresse", 'Address name', 'Nombre de la dirección', 'Non adrès la'),
  ('p-adr-etiquette-ex', 'Maison, bureau…', 'Home, office…', 'Casa, oficina…', 'Kay, biwo…'),
  ('p-adr-destinataire', 'Nom du destinataire', 'Recipient name', 'Nombre del destinatario', 'Non destinatè a'),
  ('p-adr-telephone', 'Téléphone', 'Phone', 'Teléfono', 'Telefòn'),
  ('p-adr-pays', 'Pays', 'Country', 'País', 'Peyi'),
  ('p-adr-region', 'Région', 'Region', 'Región', 'Rejyon'),
  ('p-adr-ville', 'Ville', 'City', 'Ciudad', 'Vil'),
  ('p-adr-adresse', 'Adresse', 'Address', 'Dirección', 'Adrès'),
  ('p-adr-consignes', 'Consignes', 'Instructions', 'Indicaciones', 'Konsiy'),
  ('p-adr-consignes-aide', 'Portail, étage, point de repère… (300 caractères)', 'Gate, floor, landmark… (300 characters)', 'Portón, piso, punto de referencia… (300 caracteres)', 'Pòtay, etaj, yon repè… (300 karaktè)'),
  ('p-adr-defaut', 'Utiliser comme adresse par défaut', 'Use as default address', 'Usar como dirección predeterminada', 'Itilize kòm adrès pa defo'),
  ('p-adr-nouvelle', 'Nouvelle adresse', 'New address', 'Nueva dirección', 'Nouvo adrès'),
  ('p-adr-modifier', "Modifier l'adresse", 'Edit the address', 'Modificar la dirección', 'Modifye adrès la'),
  ('p-adr-retour', 'Retour aux adresses', 'Back to addresses', 'Volver a las direcciones', 'Tounen nan adrès yo'),
  ('p-adr-confirmer', 'Supprimer cette adresse ?', 'Delete this address?', '¿Eliminar esta dirección?', 'Efase adrès sa a ?'),
  ('p-adr-supprimee', 'Adresse supprimée.', 'Address deleted.', 'Dirección eliminada.', 'Adrès la efase.'),
  ('p-adr-choisir', 'Adresse', 'Address', 'Dirección', 'Adrès'),
  ('p-adr-autre', 'Une autre adresse…', 'Another address…', 'Otra dirección…', 'Yon lòt adrès…'),
  ('p-err-adresse', "Indiquez l'adresse.", 'Enter the address.', 'Indique la dirección.', 'Make adrès la.'))

# ---- enlèvement, livraison ------------------------------------------------------------------------------------------------------------------
a(('p-enl-intro', "Demandez qu'un chauffeur passe chercher vos colis à l'adresse de votre choix. L'équipe confirme votre demande.", 'Ask for a driver to collect your parcels at the address of your choice. Our team confirms your request.',
   'Solicite que un conductor recoja sus paquetes en la dirección que elija. Nuestro equipo confirma su solicitud.', 'Mande yon chofè pase pran kolis ou yo nan adrès ou chwazi a. Ekip nou an konfime demand ou a.'),
  ('p-enl-nouveau', "Nouvelle demande d'enlèvement", 'New pickup request', 'Nueva solicitud de recogida', 'Nouvo demand ranmasaj'),
  ('p-enl-envoyer', 'Envoyer la demande', 'Send the request', 'Enviar la solicitud', 'Voye demand lan'),
  ('p-enl-mes-demandes', "Mes demandes d'enlèvement", 'My pickup requests', 'Mis solicitudes de recogida', 'Demand ranmasaj mwen yo'),
  ('p-enl-vide', "Aucune demande d'enlèvement.", 'No pickup request.', 'No hay solicitudes de recogida.', 'Pa gen demand ranmasaj.'),
  ('p-date-souhaitee', 'Date souhaitée', 'Preferred date', 'Fecha deseada', 'Dat ou swete a'),
  ('p-creneau', 'Créneau', 'Time slot', 'Franja horaria', 'Kreno'),
  ('p-colis-prevus', 'Nombre de colis', 'Number of parcels', 'Número de paquetes', 'Kantite kolis'),
  ('p-telephone-contact', 'Téléphone sur place', 'Phone on site', 'Teléfono en el lugar', 'Telefòn sou plas la'),
  ('p-notes', 'Remarques', 'Notes', 'Observaciones', 'Remak'),
  ('p-notes-aide-enl', 'Ce que le chauffeur doit savoir : accès, étage, colis volumineux…', 'What the driver should know: access, floor, bulky parcels…', 'Lo que el conductor debe saber: acceso, piso, paquetes voluminosos…', 'Sa chofè a dwe konnen : aksè, etaj, kolis ki gwo…'),
  ('p-notes-aide-liv', 'Ce que le livreur doit savoir : accès, personne à appeler…', 'What the courier should know: access, who to call…', 'Lo que el repartidor debe saber: acceso, a quién llamar…', 'Sa livrè a dwe konnen : aksè, ki moun pou rele…'),
  ('p-date', 'Date', 'Date', 'Fecha', 'Dat'),
  ('p-message-equipe', "Message de l'équipe", 'Message from our team', 'Mensaje del equipo', 'Mesaj ekip la'),
  ('p-annuler-demande', 'Annuler la demande', 'Cancel the request', 'Cancelar la solicitud', 'Anile demand lan'),
  ('p-annuler-confirmer', 'Annuler cette demande ?', 'Cancel this request?', '¿Cancelar esta solicitud?', 'Anile demand sa a ?'),
  ('p-err-date', "Choisissez une date entre aujourd'hui et dans 60 jours.", 'Choose a date between today and 60 days from now.', 'Elija una fecha entre hoy y dentro de 60 días.', 'Chwazi yon dat ant jodi a ak 60 jou apre.'),
  ('p-err-colis', 'Indiquez un nombre de colis entre 1 et 100.', 'Enter a number of parcels between 1 and 100.', 'Indique un número de paquetes entre 1 y 100.', 'Make yon kantite kolis ant 1 ak 100.'),
  ('win-ANY', 'Toute la journée', 'Any time of day', 'Todo el día', 'Tout jounen an'),
  ('win-MORNING', 'Le matin', 'Morning', 'Por la mañana', 'Maten'),
  ('win-AFTERNOON', "L'après-midi", 'Afternoon', 'Por la tarde', 'Apremidi'),
  ('p-liv-intro', "Demandez la livraison de vos colis arrivés au hub à l'adresse de votre choix. L'équipe confirme votre demande.", 'Ask for your parcels that arrived at the hub to be delivered to the address of your choice. Our team confirms your request.',
   'Solicite la entrega de sus paquetes llegados al hub en la dirección que elija. Nuestro equipo confirma su solicitud.', 'Mande livrezon kolis ou yo ki rive nan hub la nan adrès ou chwazi a. Ekip nou an konfime demand ou a.'),
  ('p-liv-aide', 'Seuls les colis disponibles au hub peuvent être livrés.', 'Only parcels available at the hub can be delivered.', 'Solo se pueden entregar los paquetes disponibles en el hub.', 'Se kolis ki disponib nan hub la sèlman ki ka livre.'),
  ('p-liv-nouveau', 'Nouvelle demande de livraison', 'New delivery request', 'Nueva solicitud de entrega', 'Nouvo demand livrezon'),
  ('p-liv-colis-au-hub', 'Colis disponibles au hub', 'Parcels available at the hub', 'Paquetes disponibles en el hub', 'Kolis disponib nan hub la'),
  ('p-liv-envoyer', 'Envoyer la demande', 'Send the request', 'Enviar la solicitud', 'Voye demand lan'),
  ('p-liv-rien-au-hub', 'Aucun colis disponible au hub pour le moment.', 'No parcel available at the hub right now.', 'No hay paquetes disponibles en el hub por ahora.', 'Pa gen kolis disponib nan hub la pou kounye a.'),
  ('p-liv-mes-demandes', 'Mes demandes de livraison', 'My delivery requests', 'Mis solicitudes de entrega', 'Demand livrezon mwen yo'),
  ('p-liv-aucune-demande', 'Aucune demande de livraison.', 'No delivery request.', 'No hay solicitudes de entrega.', 'Pa gen demand livrezon.'),
  ('p-liv-livraisons', 'Livraisons', 'Deliveries', 'Entregas', 'Livrezon'),
  ('p-liv-aucune', 'Aucune livraison pour le moment.', 'No delivery yet.', 'Aún no hay entregas.', 'Pa gen livrezon pou kounye a.'),
  ('p-err-choisir-colis', 'Choisissez au moins un colis.', 'Choose at least one parcel.', 'Elija al menos un paquete.', 'Chwazi omwen yon kolis.'))

# ---- notifications, support, profil -------------------------------------------------------------------------------------------------------------
a(('p-notif-intro', 'Les messages importants sur vos colis, vos expéditions et vos factures.', 'Important messages about your parcels, shipments and invoices.', 'Los mensajes importantes sobre sus paquetes, envíos y facturas.',
   'Mesaj enpòtan sou kolis, ekspedisyon ak fakti ou yo.'),
  ('p-notif-vide', 'Aucune notification pour le moment.', 'No notification yet.', 'Aún no hay notificaciones.', 'Pa gen notifikasyon pou kounye a.'),
  ('p-notif-non-lues', '{nombre} non lue(s)', '{nombre} unread', '{nombre} sin leer', '{nombre} pa li'),
  ('p-notif-tout-lire', 'Tout marquer comme lu', 'Mark all as read', 'Marcar todo como leído', 'Make tout kòm li'),
  ('p-notif-lire', 'Marquer comme lu', 'Mark as read', 'Marcar como leído', 'Make kòm li'),
  ('p-notif-nouvelle', 'Nouvelle', 'New', 'Nueva', 'Nouvo'),
  ('p-notif-autre', 'Nouvelle notification.', 'New notification.', 'Nueva notificación.', 'Nouvo notifikasyon.'),
  ('notif-ParcelReceived', "Votre colis {tracking_number} est arrivé à l'entrepôt.", 'Your parcel {tracking_number} has arrived at the warehouse.', 'Su paquete {tracking_number} ha llegado al almacén.', 'Kolis ou a {tracking_number} rive nan depo a.'),
  ('notif-ShipmentArrived', 'Votre expédition {shipment_code} est arrivée.', 'Your shipment {shipment_code} has arrived.', 'Su envío {shipment_code} ha llegado.', 'Ekspedisyon ou a {shipment_code} rive.'),
  ('notif-CustomsCleared', 'Votre colis {tracking_number} est dédouané.', 'Your parcel {tracking_number} has cleared customs.', 'Su paquete {tracking_number} ha sido despachado en aduana.', 'Kolis ou a {tracking_number} pase dwàn.'),
  ('notif-OutForDelivery', 'Votre colis {tracking_number} est en cours de livraison.', 'Your parcel {tracking_number} is out for delivery.', 'Su paquete {tracking_number} está en reparto.', 'Kolis ou a {tracking_number} ap livre.'),
  ('notif-Delivered', 'Votre colis {tracking_number} a été livré.', 'Your parcel {tracking_number} has been delivered.', 'Su paquete {tracking_number} ha sido entregado.', 'Kolis ou a {tracking_number} livre.'),
  ('notif-DeliveryOtp', 'Code de livraison : {code} (valable {expires_hours} h). Ne le donnez au livreur qu\'au moment de la remise du colis.', 'Delivery code: {code} (valid {expires_hours} h). Only give it to the courier when you receive the parcel.',
   'Código de entrega: {code} (válido {expires_hours} h). Solo dáselo al repartidor al recibir el paquete.', 'Kòd livrezon : {code} (valab {expires_hours} è). Pa bay livrè a li sof le w ap resevwa kolis la.'),
  # ---- phase 13 : les autres notifications (mêmes textes dans le portail ET dans les modèles d'envoi de la base) ----
  ('notif-ParcelInTransit', 'Votre colis {tracking_number} est en route.', 'Your parcel {tracking_number} is on its way.', 'Su paquete {tracking_number} está en camino.', 'Kolis ou a {tracking_number} sou wout.'),
  ('notif-ParcelArrived', 'Votre colis {tracking_number} est arrivé à destination : il passe la douane.', 'Your parcel {tracking_number} has arrived at its destination: it is going through customs.',
   'Su paquete {tracking_number} ha llegado a destino: pasa la aduana.', 'Kolis ou a {tracking_number} rive : l ap pase dwàn.'),
  ('notif-ParcelAtDestinationHub', 'Votre colis {tracking_number} est disponible au hub.', 'Your parcel {tracking_number} is available at the hub.', 'Su paquete {tracking_number} está disponible en el hub.', 'Kolis ou a {tracking_number} disponib nan hub la.'),
  ('notif-ParcelOnHold', 'Votre colis {tracking_number} est en attente. Notre équipe vous contactera si besoin.', 'Your parcel {tracking_number} is on hold. Our team will contact you if needed.',
   'Su paquete {tracking_number} está en espera. Nuestro equipo le contactará si es necesario.', 'Kolis ou a {tracking_number} an atant. Ekip nou an ap kontakte w si sa nesesè.'),
  ('notif-ParcelDamaged', 'Un incident est signalé sur votre colis {tracking_number}. Notre équipe s\'en occupe.', 'An issue has been reported on your parcel {tracking_number}. Our team is handling it.',
   'Se ha señalado una incidencia en su paquete {tracking_number}. Nuestro equipo se encarga.', 'Yo siyale yon pwoblèm sou kolis ou a {tracking_number}. Ekip nou an ap okipe l.'),
  ('notif-ParcelLost', 'Votre colis {tracking_number} est déclaré perdu. Notre équipe vous contacte.', 'Your parcel {tracking_number} has been declared lost. Our team will contact you.',
   'Su paquete {tracking_number} ha sido declarado perdido. Nuestro equipo le contactará.', 'Yo deklare kolis ou a {tracking_number} pèdi. Ekip nou an ap kontakte w.'),
  ('notif-ParcelReturned', 'Votre colis {tracking_number} est retourné à l\'expéditeur.', 'Your parcel {tracking_number} has been returned to the sender.', 'Su paquete {tracking_number} ha sido devuelto al remitente.', 'Kolis ou a {tracking_number} retounen bay moun ki voye l la.'),
  ('notif-InvoiceIssued', 'Nouvelle facture {invoice_number} : {amount} {currency}, à régler avant le {date}.', 'New invoice {invoice_number}: {amount} {currency}, due by {date}.',
   'Nueva factura {invoice_number}: {amount} {currency}, a pagar antes del {date}.', 'Nouvo fakti {invoice_number} : {amount} {currency}, pou peye anvan {date}.'),
  ('notif-InvoiceOverdue', 'La facture {invoice_number} est en retard de paiement : il reste {amount} {currency}.', 'Invoice {invoice_number} is overdue: {amount} {currency} remain to be paid.',
   'La factura {invoice_number} está vencida: quedan {amount} {currency} por pagar.', 'Fakti {invoice_number} an reta : rete {amount} {currency} pou peye.'),
  ('notif-PaymentReceived', 'Paiement reçu : {amount} {currency} pour la facture {invoice_number}. Merci !', 'Payment received: {amount} {currency} for invoice {invoice_number}. Thank you!',
   'Pago recibido: {amount} {currency} para la factura {invoice_number}. ¡Gracias!', 'Nou resevwa peman an : {amount} {currency} pou fakti {invoice_number}. Mèsi !'),
  ('notif-PickupRequestApproved', 'Votre demande d\'enlèvement est acceptée pour le {date}. {message}', 'Your pickup request is accepted for {date}. {message}',
   'Su solicitud de recogida está aceptada para el {date}. {message}', 'Demann ranmasaj ou a aksepte pou {date}. {message}'),
  ('notif-PickupRequestRejected', 'Votre demande d\'enlèvement n\'a pas pu être acceptée : {message}', 'Your pickup request could not be accepted: {message}',
   'Su solicitud de recogida no pudo ser aceptada: {message}', 'Nou pa t ka aksepte demann ranmasaj ou a : {message}'),
  ('notif-DeliveryRequestApproved', 'Votre livraison est planifiée pour le {date}. {message}', 'Your delivery is scheduled for {date}. {message}', 'Su entrega está planificada para el {date}. {message}', 'Livrezon ou a planifye pou {date}. {message}'),
  ('notif-DeliveryRequestRejected', 'Votre demande de livraison n\'a pas pu être acceptée : {message}', 'Your delivery request could not be accepted: {message}',
   'Su solicitud de entrega no pudo ser aceptada: {message}', 'Nou pa t ka aksepte demann livrezon ou a : {message}'),
  ('notif-SupportTicketAnswered', 'Notre équipe a répondu à votre message.', 'Our team has replied to your message.', 'Nuestro equipo ha respondido a su mensaje.', 'Ekip nou an reponn mesaj ou a.'),
  # les titres (objet d'un e-mail, titre d'une notification sur le téléphone)
  ('notif-titre-ParcelReceived', 'Colis reçu', 'Parcel received', 'Paquete recibido', 'Kolis resevwa'),
  ('notif-titre-ParcelInTransit', 'Colis en route', 'Parcel on its way', 'Paquete en camino', 'Kolis sou wout'),
  ('notif-titre-ParcelArrived', 'Colis arrivé', 'Parcel arrived', 'Paquete llegado', 'Kolis rive'),
  ('notif-titre-CustomsCleared', 'Colis dédouané', 'Parcel cleared', 'Paquete despachado', 'Kolis pase dwàn'),
  ('notif-titre-ParcelAtDestinationHub', 'Colis disponible', 'Parcel available', 'Paquete disponible', 'Kolis disponib'),
  ('notif-titre-OutForDelivery', 'Colis en livraison', 'Parcel out for delivery', 'Paquete en reparto', 'Kolis ap livre'),
  ('notif-titre-Delivered', 'Colis livré', 'Parcel delivered', 'Paquete entregado', 'Kolis livre'),
  ('notif-titre-ParcelOnHold', 'Colis en attente', 'Parcel on hold', 'Paquete en espera', 'Kolis an atant'),
  ('notif-titre-ParcelDamaged', 'Incident sur un colis', 'Issue with a parcel', 'Incidencia en un paquete', 'Pwoblèm sou yon kolis'),
  ('notif-titre-ParcelLost', 'Colis perdu', 'Parcel lost', 'Paquete perdido', 'Kolis pèdi'),
  ('notif-titre-ParcelReturned', 'Colis retourné', 'Parcel returned', 'Paquete devuelto', 'Kolis retounen'),
  ('notif-titre-InvoiceIssued', 'Nouvelle facture', 'New invoice', 'Nueva factura', 'Nouvo fakti'),
  ('notif-titre-InvoiceOverdue', 'Facture en retard', 'Overdue invoice', 'Factura vencida', 'Fakti an reta'),
  ('notif-titre-PaymentReceived', 'Paiement reçu', 'Payment received', 'Pago recibido', 'Peman resevwa'),
  ('notif-titre-PickupRequestApproved', 'Enlèvement accepté', 'Pickup accepted', 'Recogida aceptada', 'Ranmasaj aksepte'),
  ('notif-titre-PickupRequestRejected', 'Enlèvement refusé', 'Pickup refused', 'Recogida rechazada', 'Ranmasaj refize'),
  ('notif-titre-DeliveryRequestApproved', 'Livraison planifiée', 'Delivery scheduled', 'Entrega programada', 'Livrezon planifye'),
  ('notif-titre-DeliveryRequestRejected', 'Livraison refusée', 'Delivery refused', 'Entrega rechazada', 'Livrezon refize'),
  ('notif-titre-SupportTicketAnswered', 'Réponse du support', 'Support reply', 'Respuesta del soporte', 'Repons sipò a'),
  ('notif-titre-DeliveryOtp', 'Votre code de livraison', 'Your delivery code', 'Su código de entrega', 'Kòd livrezon ou'),
  ('p-pref-titre', 'Comment vous prévenir', 'How to notify you', 'Cómo avisarle', 'Kijan pou n avèti w'),
  ('p-pref-intro', 'Choisissez par où recevoir les nouvelles de vos colis, de vos factures et du support.', 'Choose how to receive news about your parcels, invoices and support.',
   'Elija por dónde recibir las novedades de sus paquetes, facturas y soporte.', 'Chwazi ki jan pou w resevwa nouvèl kolis, fakti ak sipò ou yo.'),
  ('p-pref-in_app', 'Dans mon espace client', 'In my customer area', 'En mi espacio de cliente', 'Nan espas kliyan mwen'),
  ('p-pref-email', 'Par e-mail', 'By e-mail', 'Por correo electrónico', 'Pa imèl'),
  ('p-pref-push', 'Sur mon téléphone (application)', 'On my phone (app)', 'En mi teléfono (aplicación)', 'Sou telefòn mwen (aplikasyon)'),
  ('p-pref-sms', 'Par SMS', 'By SMS', 'Por SMS', 'Pa SMS'),
  ('p-pref-whatsapp', 'Par WhatsApp', 'By WhatsApp', 'Por WhatsApp', 'Pa WhatsApp'),
  ('p-pref-toujours', '(toujours)', '(always)', '(siempre)', '(toujou)'),
  ('p-pref-bientot', '(bientôt : votre choix sera gardé)', '(coming soon: your choice will be kept)', '(próximamente: se guardará su elección)', '(talè konsa : n ap kenbe chwa w)'),
  ('p-pref-enregistre', 'Préférence enregistrée.', 'Preference saved.', 'Preferencia guardada.', 'Preferans anrejistre.'),
  ('p-sup-intro', "Une question, un problème ? Écrivez-nous : l'équipe vous répond ici.", 'A question, a problem? Write to us: our team replies here.', '¿Una duda, un problema? Escríbanos: el equipo le responde aquí.',
   'Yon kesyon, yon pwoblèm ? Ekri nou : ekip nou an reponn ou isit la.'),
  ('p-sup-nouveau', 'Nouvelle demande', 'New request', 'Nueva solicitud', 'Nouvo demand'),
  ('p-sup-whatsapp', 'Écrire sur WhatsApp', 'Write on WhatsApp', 'Escribir por WhatsApp', 'Ekri sou WhatsApp'),
  ('p-sup-vide', 'Aucune demande de support.', 'No support request.', 'No hay solicitudes de soporte.', 'Pa gen demand sipò.'),
  ('p-sup-n-messages', '{nombre} message(s)', '{nombre} message(s)', '{nombre} mensaje(s)', '{nombre} mesaj'),
  ('p-sup-maj', 'Mis à jour le {date}', 'Updated on {date}', 'Actualizado el {date}', 'Mete ajou le {date}'),
  ('p-sup-reponse-equipe', "L'équipe a répondu", 'Our team has replied', 'El equipo ha respondido', 'Ekip la reponn'),
  ('p-sup-retour', 'Retour au support', 'Back to support', 'Volver a soporte', 'Tounen nan sipò a'),
  ('p-sup-categorie', 'Sujet', 'Topic', 'Tema', 'Sijè'),
  ('p-sup-sujet', 'Titre de votre demande', 'Title of your request', 'Título de su solicitud', 'Tit demand ou a'),
  ('p-sup-colis-facultatif', 'Numéro de colis (facultatif)', 'Parcel number (optional)', 'Número de paquete (opcional)', 'Nimewo kolis (opsyonèl)'),
  ('p-sup-facture-facultatif', 'Numéro de facture (facultatif)', 'Invoice number (optional)', 'Número de factura (opcional)', 'Nimewo fakti (opsyonèl)'),
  ('p-sup-message', 'Votre message', 'Your message', 'Su mensaje', 'Mesaj ou a'),
  ('p-sup-envoyer', 'Envoyer', 'Send', 'Enviar', 'Voye'),
  ('p-sup-messages', 'Messages de la demande', 'Messages of the request', 'Mensajes de la solicitud', 'Mesaj demand lan'),
  ('p-sup-repondre', 'Votre réponse', 'Your reply', 'Su respuesta', 'Repons ou a'),
  ('p-sup-envoyer-reponse', 'Envoyer la réponse', 'Send the reply', 'Enviar la respuesta', 'Voye repons lan'),
  ('p-sup-fermer', 'Fermer la demande', 'Close the request', 'Cerrar la solicitud', 'Fèmen demand lan'),
  ('p-sup-fermer-confirmer', 'Fermer cette demande ? Vous pourrez en ouvrir une autre.', 'Close this request? You can open another one.', '¿Cerrar esta solicitud? Podrá abrir otra.', 'Fèmen demand sa a ? Ou ka louvri yon lòt.'),
  ('p-sup-ferme', 'Cette demande est fermée. Ouvrez-en une nouvelle si besoin.', 'This request is closed. Open a new one if needed.', 'Esta solicitud está cerrada. Abra una nueva si lo necesita.', 'Demand sa a fèmen. Louvri yon nouvo si w bezwen.'),
  ('p-sup-facture', 'Facture', 'Invoice', 'Factura', 'Fakti'),
  ('p-err-sujet', 'Le titre doit compter au moins 3 caractères.', 'The title must have at least 3 characters.', 'El título debe tener al menos 3 caracteres.', 'Tit la dwe gen omwen 3 karaktè.'),
  ('p-err-message', 'Écrivez votre message.', 'Write your message.', 'Escriba su mensaje.', 'Ekri mesaj ou a.'),
  ('cat-PARCEL', 'Un colis', 'A parcel', 'Un paquete', 'Yon kolis'),
  ('cat-INVOICE', 'Une facture', 'An invoice', 'Una factura', 'Yon fakti'),
  ('cat-PICKUP', 'Un enlèvement', 'A pickup', 'Una recogida', 'Yon ranmasaj'),
  ('cat-DELIVERY', 'Une livraison', 'A delivery', 'Una entrega', 'Yon livrezon'),
  ('cat-ACCOUNT', 'Mon compte', 'My account', 'Mi cuenta', 'Kont mwen'),
  ('cat-OTHER', 'Autre sujet', 'Other topic', 'Otro tema', 'Lòt sijè'),
  ('tk-OPEN', 'Ouvert', 'Open', 'Abierto', 'Ouvè'),
  ('tk-ANSWERED', 'Répondu', 'Answered', 'Respondido', 'Reponn'),
  ('tk-CLOSED', 'Fermé', 'Closed', 'Cerrado', 'Fèmen'),
  ('tk-author-CUSTOMER', 'Vous', 'You', 'Usted', 'Ou menm'),
  ('tk-author-STAFF', "L'équipe Speed Express", 'The Speed Express team', 'El equipo de Speed Express', 'Ekip Speed Express la'),
  ('p-profil-intro', 'Vos informations, votre mot de passe et de quoi nous joindre.', 'Your details, your password and how to reach us.', 'Sus datos, su contraseña y cómo contactarnos.', 'Enfòmasyon ou, modpas ou ak ki jan pou kontakte nou.'))

# ---- les codes d'erreur du noyau -------------------------------------------------------------------------------------------------------------------------
a(('erreur-introuvable', "Introuvable : cet élément n'existe pas ou n'est pas à vous.", 'Not found: this item does not exist or is not yours.', 'No encontrado: este elemento no existe o no es suyo.', 'Pa jwenn : eleman sa a pa egziste oswa li pa pou ou.'),
  ('erreur-etat-incompatible', "Cette action n'est plus possible : l'élément a déjà été traité.", 'This action is no longer possible: the item has already been processed.', 'Esta acción ya no es posible: el elemento ya fue tramitado.',
   'Aksyon sa a pa posib ankò : eleman sa a deja trete.'),
  ('erreur-donnee-invalide', "Une information n'est pas valide. Vérifiez et réessayez.", 'Some information is not valid. Check it and try again.', 'Algún dato no es válido. Compruébelo e inténtelo de nuevo.',
   'Yon enfòmasyon pa valid. Verifye l epi eseye ankò.'),
  ('erreur-doublon', 'Cette demande a déjà été envoyée avec d\'autres informations. Rechargez la page.', 'This request was already sent with different details. Reload the page.', 'Esta solicitud ya se envió con otros datos. Recargue la página.',
   'Demand sa a deja voye ak lòt enfòmasyon. Rechaje paj la.'),
  ('erreur-noyau-absent', "Cette fonction n'est pas encore disponible.", 'This feature is not available yet.', 'Esta función aún no está disponible.', 'Fonksyon sa a poko disponib.'))

# ---------------------------------------------------------------------------------------------------------------------------------------------------------
BRACES = re.compile(r'\{[a-z_]+\}')
# Les modèles d'envoi de la base (outils/logistique/010-notifications.sql) : les MÊMES textes que le portail, pour qu'un e-mail ou une
# notification sur le téléphone dise exactement ce que le client lit dans son espace.
SQL_MODELES = SITE / 'outils/logistique/010-notifications.sql'
D3, F3 = '-- modeles:debut', '-- modeles:fin'
MODELES = ['ParcelReceived', 'ParcelInTransit', 'ParcelArrived', 'CustomsCleared', 'ParcelAtDestinationHub', 'OutForDelivery', 'Delivered', 'ParcelOnHold', 'ParcelDamaged',
           'ParcelLost', 'ParcelReturned', 'InvoiceIssued', 'InvoiceOverdue', 'PaymentReceived', 'PickupRequestApproved', 'PickupRequestRejected', 'DeliveryRequestApproved',
           'DeliveryRequestRejected', 'SupportTicketAnswered', 'DeliveryOtp']


def sql_texte(x):
    return "'" + x.replace("'", "''") + "'"


def ecrire_modeles(existant):
    # Si le dictionnaire a déjà une traduction pour ce français, c'est elle que le portail affiche : l'e-mail dit la même chose.
    par_cle = {cle: (fr,) + tuple(existant.get(fr, (en, es, ht))) for cle, fr, en, es, ht in T}
    lignes = []
    for code in MODELES:
        titre, corps = par_cle['notif-titre-' + code], par_cle['notif-' + code]
        for i, langue in enumerate(('fr', 'en', 'es', 'ht')):
            lignes.append('  (%s, %s, %s, %s)' % (sql_texte(code), sql_texte(langue), sql_texte(titre[i]), sql_texte(corps[i])))
    bloc = (D3 + '\n-- Écrit par outils/portail-textes.py : ne pas modifier à la main.\n'
            'insert into logistics.notification_template (code, language, title, body) values\n' + ',\n'.join(lignes) + '\n'
            'on conflict (code, language) do update set title = excluded.title, body = excluded.body\n'
            '  where (logistics.notification_template.title, logistics.notification_template.body) is distinct from (excluded.title, excluded.body);\n' + F3)
    g = SQL_MODELES.read_text(encoding='utf-8')
    assert D3 in g and F3 in g, 'repères des modèles absents de 010-notifications.sql'
    SQL_MODELES.write_text(re.sub(re.escape(D3) + r'.*?' + re.escape(F3), lambda m: bloc, g, flags=re.S), encoding='utf-8')



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
    ecrire_modeles(existant)
    print('portail : %d textes, %d entrées de dictionnaire (%d déjà connues, dont %d avec une formulation différente : celle du dictionnaire fait foi)' % (len(T), len(lignes), len(par_fr) - len(lignes), len(autres)))
    if '--detail' in sys.argv:
        print('\n'.join('  ' + x for x in autres))


if __name__ == '__main__':
    main()
