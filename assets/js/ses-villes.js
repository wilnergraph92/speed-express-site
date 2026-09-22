/* ==========================================================================
   Speed Express Shipping — villes de livraison
   --------------------------------------------------------------------------
   Le champ « Ville de livraison » du tableau de bord se remplit à partir de
   cette liste, selon le pays choisi juste avant.

   Haïti : les 140 communes, par département.
   République dominicaine : les municipios, par province.
   États-Unis : les villes où le service livre réellement — il y a près de
   vingt mille communes aux États-Unis, une liste complète n'aurait aucun
   sens dans un menu déroulant.

   Aucune liste n'est jamais complète : le formulaire garde toujours une
   entrée « Autre ville… » qui ouvre un champ libre. Une commune oubliée ici
   n'empêche donc jamais d'enregistrer un colis.

   Les noms sont des noms propres : le sélecteur de langue ne les traduit pas.
   ========================================================================== */
window.SES_VILLES = {

  HT: [
    ['Ouest', ['Port-au-Prince', 'Delmas', 'Pétion-Ville', 'Carrefour', 'Tabarre',
      'Cité Soleil', 'Croix-des-Bouquets', 'Kenscoff', 'Gressier', 'Thomazeau',
      'Ganthier', 'Cornillon', 'Fonds-Verrettes', 'Léogâne', 'Petit-Goâve',
      'Grand-Goâve', 'Arcahaie', 'Cabaret', 'Anse-à-Galets', 'Pointe-à-Raquette']],

    ['Sud-Est', ['Jacmel', 'Cayes-Jacmel', 'Marigot', 'La Vallée-de-Jacmel', 'Bainet',
      'Côtes-de-Fer', 'Belle-Anse', 'Grand-Gosier', 'Thiotte', 'Anse-à-Pitres']],

    ['Nord', ['Cap-Haïtien', 'Limonade', 'Quartier-Morin', 'Acul-du-Nord',
      'Plaine-du-Nord', 'Milot', 'Grande-Rivière-du-Nord', 'Bahon', 'Dondon',
      'Saint-Raphaël', 'Pignon', 'La Victoire', 'Ranquitte', 'Borgne',
      'Port-Margot', 'Limbé', 'Bas-Limbé', 'Pilate', 'Plaisance']],

    ['Nord-Est', ['Fort-Liberté', 'Ferrier', 'Perches', 'Ouanaminthe', 'Capotille',
      'Mont-Organisé', 'Trou-du-Nord', 'Sainte-Suzanne', 'Terrier-Rouge',
      'Caracol', 'Vallières', 'Carice', 'Mombin-Crochu']],

    ['Nord-Ouest', ['Port-de-Paix', 'Bassin-Bleu', 'Chansolme', 'Île de la Tortue',
      'Saint-Louis-du-Nord', 'Anse-à-Foleur', 'Jean-Rabel', 'Môle-Saint-Nicolas',
      'Bombardopolis', 'Baie-de-Henne']],

    ['Artibonite', ['Gonaïves', 'Ennery', 'L\'Estère', 'Dessalines', 'Desdunes',
      'Grande-Saline', 'Petite-Rivière-de-l\'Artibonite', 'Saint-Marc', 'La Chapelle',
      'Verrettes', 'Saint-Michel-de-l\'Attalaye', 'Marmelade', 'Anse-Rouge',
      'Gros-Morne', 'Terre-Neuve']],

    ['Centre', ['Hinche', 'Maïssade', 'Thomonde', 'Cerca-Carvajal', 'Mirebalais',
      'Saut-d\'Eau', 'Boucan-Carré', 'Lascahobas', 'Belladère', 'Savanette',
      'Cerca-la-Source', 'Thomassique']],

    ['Grand\'Anse', ['Jérémie', 'Abricots', 'Bonbon', 'Moron', 'Chambellan',
      'Dame-Marie', 'Anse-d\'Hainault', 'Les Irois', 'Corail', 'Roseaux',
      'Beaumont', 'Pestel']],

    ['Nippes', ['Miragoâne', 'Fonds-des-Nègres', 'Paillant', 'Petite-Rivière-de-Nippes',
      'Anse-à-Veau', 'Arnaud', 'L\'Asile', 'Plaisance-du-Sud', 'Petit-Trou-de-Nippes',
      'Baradères', 'Grand-Boucan']],

    ['Sud', ['Les Cayes', 'Île-à-Vache', 'Torbeck', 'Chantal', 'Camp-Perrin',
      'Maniche', 'Aquin', 'Cavaillon', 'Saint-Louis-du-Sud', 'Saint-Jean-du-Sud',
      'Arniquet', 'Port-Salut', 'Roche-à-Bateau', 'Coteaux', 'Port-à-Piment',
      'Chardonnières', 'Les Anglais', 'Tiburon']]
  ],

  DO: [
    ['Distrito Nacional', ['Santo Domingo']],

    ['Santo Domingo', ['Santo Domingo Este', 'Santo Domingo Norte', 'Santo Domingo Oeste',
      'Boca Chica', 'Los Alcarrizos', 'Pedro Brand', 'San Antonio de Guerra']],

    ['Santiago', ['Santiago de los Caballeros', 'Villa González', 'Tamboril',
      'Licey al Medio', 'Puñal', 'Sabana Iglesia', 'Jánico', 'San José de las Matas',
      'Villa Bisonó (Navarrete)']],

    ['San Cristóbal', ['San Cristóbal', 'Bajos de Haina', 'Villa Altagracia', 'Yaguate',
      'Cambita Garabitos', 'Los Cacaos', 'Sabana Grande de Palenque',
      'San Gregorio de Nigua']],

    ['La Vega', ['La Vega', 'Constanza', 'Jarabacoa', 'Jima Abajo']],

    ['Puerto Plata', ['Puerto Plata', 'Sosúa', 'Imbert', 'Altamira', 'Luperón',
      'Villa Isabela', 'Los Hidalgos', 'Guananico', 'Villa Montellano']],

    ['Duarte', ['San Francisco de Macorís', 'Villa Riva', 'Pimentel', 'Castillo',
      'Las Guáranas', 'Arenoso', 'Eugenio María de Hostos']],

    ['La Altagracia', ['Higüey', 'Punta Cana', 'San Rafael del Yuma']],

    ['La Romana', ['La Romana', 'Guaymate', 'Villa Hermosa']],

    ['San Pedro de Macorís', ['San Pedro de Macorís', 'Consuelo', 'Quisqueya',
      'Ramón Santana', 'Guayacanes', 'Los Llanos']],

    ['Espaillat', ['Moca', 'Gaspar Hernández', 'Cayetano Germosén', 'Jamao al Norte',
      'San Víctor']],

    ['Monseñor Nouel', ['Bonao', 'Maimón', 'Piedra Blanca']],

    ['Sánchez Ramírez', ['Cotuí', 'Cevicos', 'Fantino', 'La Mata']],

    ['María Trinidad Sánchez', ['Nagua', 'Cabrera', 'Río San Juan', 'El Factor']],

    ['Samaná', ['Samaná', 'Las Terrenas', 'Sánchez']],

    ['Hermanas Mirabal', ['Salcedo', 'Tenares', 'Villa Tapia']],

    ['Valverde', ['Mao', 'Esperanza', 'Laguna Salada']],

    ['Santiago Rodríguez', ['San Ignacio de Sabaneta', 'Monción', 'Los Almácigos']],

    ['Dajabón', ['Dajabón', 'Loma de Cabrera', 'Partido', 'Restauración', 'El Pino']],

    ['Montecristi', ['Montecristi', 'Castañuelas', 'Guayubín', 'Las Matas de Santa Cruz',
      'Pepillo Salcedo', 'Villa Vásquez']],

    ['San Juan', ['San Juan de la Maguana', 'Bohechío', 'El Cercado', 'Juan de Herrera',
      'Las Matas de Farfán', 'Vallejuelo']],

    ['Elías Piña', ['Comendador', 'Bánica', 'El Llano', 'Hondo Valle', 'Juan Santiago',
      'Pedro Santana']],

    ['Azua', ['Azua de Compostela', 'Estebanía', 'Guayabal', 'Las Charcas',
      'Las Yayas de Viajama', 'Padre Las Casas', 'Peralta', 'Pueblo Viejo',
      'Sabana Yegua', 'Tábara Arriba']],

    ['San José de Ocoa', ['San José de Ocoa', 'Rancho Arriba', 'Sabana Larga']],

    ['Peravia', ['Baní', 'Nizao', 'Matanzas']],

    ['Monte Plata', ['Monte Plata', 'Bayaguana', 'Sabana Grande de Boyá', 'Yamasá',
      'Peralvillo']],

    ['Hato Mayor', ['Hato Mayor del Rey', 'Sabana de la Mar', 'El Valle']],

    ['El Seibo', ['El Seibo', 'Miches']],

    ['Barahona', ['Barahona', 'Cabral', 'Enriquillo', 'Paraíso', 'Polo', 'Vicente Noble',
      'El Peñón', 'Fundación', 'Jaquimeyes', 'La Ciénaga', 'Las Salinas']],

    ['Bahoruco', ['Neiba', 'Galván', 'Los Ríos', 'Tamayo', 'Villa Jaragua']],

    ['Independencia', ['Jimaní', 'Duvergé', 'La Descubierta', 'Mella', 'Postrer Río',
      'Cristóbal']],

    ['Pedernales', ['Pedernales', 'Oviedo']]
  ],

  US: [
    ['Florida', ['Miami', 'Miami Gardens', 'Miami Beach', 'North Miami',
      'North Miami Beach', 'Hialeah', 'Opa-locka', 'Aventura', 'Homestead',
      'Hollywood', 'Fort Lauderdale', 'Pembroke Pines', 'Miramar', 'Lauderhill',
      'Plantation', 'Sunrise', 'Coral Springs', 'Pompano Beach', 'Deerfield Beach',
      'Boca Raton', 'Delray Beach', 'West Palm Beach', 'Lake Worth', 'Port St. Lucie',
      'Fort Pierce', 'Orlando', 'Kissimmee', 'Tampa', 'Jacksonville', 'Naples',
      'Immokalee', 'Fort Myers']],

    ['New York', ['New York', 'Brooklyn', 'Queens', 'Bronx', 'Staten Island',
      'Mount Vernon', 'Yonkers', 'New Rochelle', 'Spring Valley', 'Nyack',
      'Hempstead', 'Elmont', 'Rochester', 'Buffalo']],

    ['New Jersey', ['Newark', 'Jersey City', 'Elizabeth', 'Irvington', 'East Orange',
      'Orange', 'Paterson', 'Union City', 'Plainfield', 'Trenton']],

    ['Massachusetts', ['Boston', 'Dorchester', 'Mattapan', 'Hyde Park', 'Brockton',
      'Randolph', 'Everett', 'Malden', 'Somerville', 'Cambridge', 'Lynn',
      'Lawrence', 'Worcester', 'Springfield']],

    ['Connecticut', ['Bridgeport', 'Hartford', 'New Haven', 'Stamford', 'Norwalk',
      'Waterbury']],

    ['Georgia', ['Atlanta', 'Decatur', 'Marietta', 'Savannah']],

    ['Maryland', ['Baltimore', 'Silver Spring', 'Hyattsville']],

    ['District of Columbia', ['Washington']],

    ['Pennsylvania', ['Philadelphia', 'Pittsburgh']],

    ['Illinois', ['Chicago']],

    ['Texas', ['Houston', 'Dallas', 'Austin', 'San Antonio']],

    ['California', ['Los Angeles', 'San Francisco', 'San Diego', 'Oakland']],

    ['North Carolina', ['Charlotte', 'Raleigh', 'Durham']]
  ]
};
