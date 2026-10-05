# Changelog

Toutes les évolutions importantes de **Planche-Contact** seront documentées dans ce fichier.

Le projet suit autant que possible les recommandations de **Keep a Changelog** et du **Versioning Sémantique (SemVer)**.

## [Non publié]

### Ajouté

- **Section « avancée » dans l'interface graphique, pour la mise en page, les légendes et le thème graphique** (cahier des charges §2/§4, suite de l'option `--profile` déjà disponible en CLI) : repliée par défaut (`Gtk.Expander`), séparée des réglages simples existants (nombre de photos/format, inchangés). Expose le modèle de mise en page (grille/paysage/portrait/grandes vignettes/libre, avec colonnes/lignes pour le modèle libre), l'orientation, le mode d'ajustement des vignettes, les marges/espacements, la position/zone/nombre de lignes/police/alignement des légendes et les champs à afficher (nom de fichier, date, appareil, objectif, focale, focale équivalente 35 mm, ouverture, vitesse, ISO, dimensions, position GPS - avec avertissement dédié, désactivée par défaut), et les couleurs personnalisées du thème graphique (le choix du thème lui-même - Clair/Sombre/Neutre/Système - se fait dans la fenêtre principale, voir « Corrigé » ci-dessous). Boutons « Enregistrer le profil… »/« Charger un profil… » (sélecteur de fichier natif) pour réutiliser un réglage d'une session à l'autre. Un profil n'est transmis au CLI (`--profile`, fichier temporaire) que s'il diffère réellement du comportement par défaut - aucun changement pour qui n'ouvre jamais cette section.
- **Véritable aperçu avant génération** (cahier des charges §3) : un bouton « Aperçu de la planche… » affiche, dans une fenêtre dédiée, la planche telle qu'elle sera réellement produite (mise en page, légendes, thème et filigrane compris), sur les premières photos du dossier d'entrée - avec le même nombre de photos que la génération réelle y placerait (réduit par le modèle « grandes vignettes » le cas échéant). Génération faite dans un sous-processus CLI séparé (nouvelle option interne `--preview-output`, qui produit une planche unique en PNG puis s'arrête sans jamais toucher au dossier de sortie réel ni générer de PDF/CSV/galerie HTML) plutôt que directement dans l'application graphique : un essai initial avec un appel direct, dans un fil d'arrière-plan de l'application, a révélé à l'usage une concurrence réelle entre le rendu de texte de Pillow (titre/numéro de page) et Pango (texte de l'interface GTK elle-même, dont la boucle principale reste active pendant ce temps) sur la bibliothèque FreeType partagée par les deux - pouvant corrompre le calcul de la taille d'un glyphe au point de faire échouer le rendu. Le sous-processus, totalement dépourvu de fenêtre ou de boucle GTK, élimine cette concurrence structurellement.
- **Nouvelle option `--profile fichier.json`** (cahier des charges §2/§4.4) : charge un profil de mise en page/légendes/thème réutilisable (voir `portfolio/presentation/profile.py`, `save_profile()`/`load_profile()`) et l'applique à la génération (planches JPEG/PDF et galerie HTML). Un fichier absent, illisible ou invalide retombe silencieusement sur le profil par défaut (comportement actuel inchangé), sans jamais interrompre la génération. En cas d'utilisation combinée avec `--format`/`--num` : ces derniers ne l'emportent sur le profil que s'ils sont explicitement différents de leur valeur par défaut ET que le profil n'a, lui, pas déjà personnalisé ce même réglage (sinon le profil, plus spécifique, l'emporte silencieusement - voir `Config.__post_init__`). Pas encore d'interface graphique pour créer ces profils (étape ultérieure) : à écrire/modifier à la main pour l'instant.

### Corrigé

- **Latent, pas encore atteignable depuis l'interface** : la pagination de `portfolio.py` (`main()`) répartissait les photos par lots de `config.num_per_sheet` directement, sans tenir compte de la réduction que le modèle « grandes vignettes » (« large_thumbs ») peut s'appliquer à lui-même (voir `presentation.layout_engine.compute_effective_per_page`) pour garantir de grandes vignettes quel que soit le nombre demandé. Les photos excédentaires d'une page ainsi trop chargée auraient été silencieusement perdues (jamais reportées sur une page supplémentaire) - corrigé en paginant sur ce nombre EFFECTIF plutôt que sur le réglage brut. Aucune régression possible aujourd'hui (le CLI n'expose pas encore de sélection de modèle/Profil - étape `--profile` à venir), corrigé par anticipation et verrouillé par un nouveau test (`tests/test_portfolio_cli.py`, qui échoue bien sans le correctif : 1 page générée au lieu des 3 attendues pour 20 photos).
- **Trois textes restaient figés en français quelle que soit la langue choisie (`--language`/interface graphique)**, trouvés lors d'un test de charge complet (60 photos, profil avancé thème sombre + légendes + filigrane, `--language en`) : le numéro de page et la mention « Planche générée par Planche-Contact » dessinés directement sur chaque planche JPEG/PDF (`contactsheet.py`, jamais raccordés à `portfolio.i18n`), l'en-tête de l'index CSV (`csvindex.py`, « Numéro »/« Fichier » codés en dur), et les unités de taille de fichier affichées dans la visionneuse de la galerie HTML (`utils.format_file_size()`, toujours « Ko »/« Mo » avec virgule décimale). Les quatre langues disposent désormais des clés correspondantes (`sheet.*`, `csv.*`, `unit.*`), vérifiées identiques dans les 4 fichiers de langue et testées de bout en bout dans les 4 langues (planche, CSV et galerie HTML).
- **Cause plus profonde du bug de taille de fichier ci-dessus** : la galerie HTML régénère les images pleine taille/vignettes dans des processus worker séparés (`ProcessPoolExecutor` en mode `spawn`, pour les mêmes raisons de performance que la génération des planches). `spawn` démarre un interpréteur Python entièrement neuf par worker, qui n'hérite d'aucun état du processus principal : `set_language()` (appelé une seule fois au démarrage du CLI) n'avait donc jamais eu lieu dans ces workers, et tout `_()` y retombait silencieusement sur l'anglais - manifeste uniquement en dehors du français (langue de repli actuelle de `_()`... mais l'anglais du bug ci-dessus le rendait visible). Corrigé en propageant explicitement la langue déjà résolue dans l'`initializer` du `ProcessPoolExecutor` (même mécanisme déjà utilisé pour reconfigurer le logging dans ces workers), qui l'applique via `set_language()` avant tout traitement. Point d'attention pour tout futur ajout de texte traduit dans du code exécuté par ces workers (`contactsheet.py`/`thumbnail.py` en sont pour l'instant protégés : tout leur texte traduit s'exécute dans le processus principal).
- **Légendes se chevauchant et illisibles sur les planches contact (JPEG/PDF)**, signalé par l'utilisateur. Deux défauts distincts dans le dessin des légendes (`contactsheet.py`/`presentation/layout_engine.py`), tous deux présents dès l'introduction des légendes personnalisables et jamais couverts par les tests existants (qui ne combinaient jamais plusieurs champs sur une ligne, ni plusieurs lignes avec une grande police) :
  - **Débordement horizontal** (le cas le plus visible, dès la configuration par défaut d'une légende à plusieurs champs) : `_draw_caption()` ne limitait jamais la largeur du texte dessiné à celle de la cellule - plusieurs champs joints sur une même ligne (ex : nom de fichier + date + appareil + ISO) produisaient un texte bien plus large qu'une vignette, débordant alors massivement dans les colonnes voisines, à gauche comme à droite. Corrigé dans un premier temps par une troncature avec ellipsis (« … ») dès qu'une ligne dépasse la largeur disponible (nouvelle fonction `_fit_text_to_width()`) - évitait tout chevauchement mais coupait l'information en pratique : remplacée par un retour à la ligne, voir l'entrée suivante (la troncature ne subsiste que comme dernier filet de sécurité).
  - **Débordement vertical** (moins visible, nécessite plusieurs lignes et/ou une police agrandie) : la hauteur réservée pour la légende suivait uniquement `caption_area_mm` (réglage indépendant, resté à sa valeur par défaut de 8 mm si l'utilisateur augmente `lines`/la taille de police sans y penser), si bien que les dernières lignes débordaient dans la photo de la rangée suivante. `layout_engine._reserve_caption_px()` réserve désormais le MAXIMUM entre `caption_area_mm` et la hauteur réellement nécessaire pour le nombre de lignes/la taille de police configurés - jamais la première valeur seule.
  - La constante d'espacement entre deux lignes de légende (auparavant dupliquée : `+ 4` codé en dur indépendamment dans `contactsheet.py` et implicitement supposée par le moteur de mise en page) est désormais centralisée (`presentation.CAPTION_LINE_SPACING_PX`), pour que les deux ne puissent plus diverger.
  - Le PDF (`portfolio.pdf`) embarque directement les mêmes images JPEG que les planches contact : ce correctif s'applique donc aussi à lui, sans changement séparé. La galerie HTML n'était pas concernée (le texte y suit le flux normal du navigateur, qui enveloppe une légende trop longue plutôt que de la faire déborder).
  - Verrouillé par 3 nouveaux tests (`tests/test_contactsheet.py`, `tests/test_layout_engine.py`), qui échouent bien sans le correctif.
- **Informations de légende tronquées par « … » sous les photos (planches contact JPEG/PDF)**, signalé par l'utilisateur juste après le correctif de chevauchement ci-dessus : la troncature par ellipsis qu'il avait introduite supprimait bien tout chevauchement, mais coupait en pratique la plupart des légendes à plusieurs champs (réglage par défaut « Lignes de texte » = 1 : tous les champs cochés sur UNE seule ligne, bien plus large qu'une vignette - une grande partie de l'information disparaissait). Les légendes passent désormais à la ligne : `presentation.captions.layout_caption_lines()` remplit les lignes champ par champ, en passant à la ligne AVANT le champ qui ferait dépasser la largeur de la vignette. Un champ n'est jamais coupé en deux tant qu'il tient seul sur une ligne ; un champ trop long à lui seul (ex : un nom d'objectif) passe à la ligne aux espaces ; le séparateur n'apparaît jamais en début ni en fin de ligne. « Lignes de texte » reste le nombre de lignes sur lequel les champs sont d'abord répartis (résultat strictement identique à avant quand tout tient déjà), mais le nombre de lignes réellement affichées peut désormais être plus élevé.
  - Ce nombre de lignes dépend du texte réel, donc de la largeur de la vignette, elle-même dépendante de la hauteur réservée aux légendes : `ContactSheetGenerator._plan_page()` mesure le texte passé à la ligne puis recalcule la mise en page jusqu'à stabilité (`compute_page_layout(..., caption_lines=...)`, plafonné à 10 lignes). Les vignettes rapetissent juste assez pour réserver la hauteur nécessaire - jamais de chevauchement. Chaque planche ajuste ainsi la hauteur de légende à ses propres photos (une page dont une photo a un nom d'objectif très long peut avoir des vignettes légèrement plus petites que la précédente).
  - La troncature « … » ne subsiste que comme dernier filet de sécurité : un mot isolé plus large que la cellule, ou des lignes en trop au-delà de la hauteur disponible (typiquement une légende « à droite » sur une petite vignette).
  - Sans légende, aucune métadonnée EXIF n'est lue (inchangé, verrouillé par un test). Le PDF reprend les mêmes JPEG et en profite automatiquement ; la galerie HTML n'était pas concernée (le navigateur gère lui-même le retour à la ligne).
  - Verrouillé par 12 nouveaux tests (`tests/test_captions.py`, `tests/test_layout_engine.py`, `tests/test_contactsheet.py`).
- **Choix du thème introuvable dans la fenêtre principale**, signalé par l'utilisateur : le menu Clair/Sombre/Neutre/Système n'existait que dans la section « Réglages avancés », repliée par défaut - pour un réglage visuel aussi courant, ce n'était pas découvrable. Il est désormais dans la fenêtre principale (liste « Thème », sur la ligne de l'opacité du filigrane, avec une infobulle décrivant les quatre modes) ; la section avancée ne garde que les couleurs personnalisées (« Couleurs du thème »), qui remplacent celles du thème choisi. Ce menu est l'UNIQUE widget du mode de thème (aucun doublon à garder synchronisé) : il alimente le Profil comme avant (`_profile_from_widgets()`/`_apply_profile_to_widgets()`), si bien que profil enregistré/chargé, aperçu, « Réinitialiser » et transmission au CLI (`--profile`, uniquement si le profil diffère du défaut) fonctionnent sans autre changement - vérifié en pilotant la vraie interface sous GTK4/Xvfb. Clés de traduction `gen.theme_*` ajoutées dans les 4 langues, `adv.theme_mode*` retirées.
  - **Mode « Système » mal décrit dans le manuel (4 langues)** : il affirmait que les planches/PDF suivaient les préférences du système d'exploitation. C'est faux : une planche JPEG/PDF est une image fixe et `resolve_theme()` n'est jamais appelée avec `prefer_dark` - elles restent claires dans ce mode ; seule la galerie HTML suit le navigateur de chaque visiteur. Manuels corrigés (l'ancien libellé du menu, « Système (galerie HTML uniquement) », le disait déjà) et infobulle ajoutée.
  - Infobulle sur « Lignes de texte » : précise que le texte passe de lui-même à la ligne s'il est trop large (voir ci-dessus).
  - Nouveau `tests/test_i18n.py` (6 tests) : mêmes clés dans les 4 langues, toute clé de traduction littérale utilisée dans le code existe, options du menu de thème traduites dans chaque langue.
- **Vide entre une photo en paysage et sa légende (planches JPEG/PDF)**, signalé par l'utilisateur : une vignette garde ses proportions (`Image.thumbnail`), donc une photo 4:3 n'occupe que les trois quarts de sa cellule carrée, collée en haut à gauche, alors que la légende démarrait sous la CELLULE - un vide d'un quart de vignette les séparait (et une photo en portrait restait calée à gauche au-dessus d'une légende centrée). La photo est désormais posée sur sa légende (`contactsheet._thumb_offset()`) : alignée en bas pour « sous la photo », en haut pour « au-dessus », contre la légende pour « à droite » ; horizontalement elle suit l'alignement du texte (gauche/centre/droite). Le vide passe du côté opposé à la légende : chaque photo est regroupée avec son texte et les légendes restent alignées d'une photo à l'autre.
  - Un petit écart voulu (`presentation.CAPTION_PHOTO_GAP_PX`, ~1,5 mm) est réservé entre la photo et son texte par le moteur de mise en page, EN PLUS de la zone de texte (qui reste exactement « Zone de légende (mm) ») : il s'ajoute au pas entre rangées/colonnes, donc les vignettes rapetissent très légèrement quand une légende est affichée. Sans lui, le haut des lettres touchait presque le bord d'une photo qui remplit sa cellule.
  - Sans légende effectivement dessinée (position « Aucune », ou aucun champ coché), rien ne change : mêmes positions et mêmes tailles qu'avant (verrouillé par des tests).
  - Verrouillé par 14 nouveaux tests (`tests/test_layout_engine.py`, `tests/test_contactsheet.py`) ; 3 tests existants (légende exactement collée à la photo) mis à jour pour inclure l'écart.
- **« Remplir » (mode d'ajustement des vignettes) ne recadrait rien**, constaté en préparant le correctif précédent : le réglage « Ajustement de la photo » (Entière / Remplir) de la section avancée était bien enregistré dans le Profil (JSON, aperçu, profils enregistrés) et décrit dans le manuel, mais aucun code de rendu ne le lisait - les vignettes étaient toujours « Entières ». Il est désormais câblé de bout en bout : en mode « Remplir » (`fit_mode="cover"`), chaque photo est recadrée au centre en carré pour remplir toute sa cellule, sans marge vide (planches JPEG, donc aussi PDF et aperçu). Une seule règle de recadrage, `thumbnail.fit_thumbnail_image()`, partagée par la génération parallèle (processus `spawn`, à qui le mode est transmis explicitement) et la version unitaire. La géométrie de la grille ne change pas (les cellules sont déjà carrées). Mode « Entière » (défaut) strictement inchangé.
  - Une photo plus petite que sa cellule n'est jamais agrandie, dans aucun des deux modes (règle de `Image.thumbnail`, conservée) : en « Remplir », une photo dont le petit côté est inférieur à la cellule donne un carré plus petit que la cellule, placé comme les autres vignettes. Sans effet pour des photos d'appareil photo ordinaires, bien plus grandes qu'une cellule.
  - RAW : en « Remplir », l'aperçu embarqué du RAW n'est jugé assez grand que si son PETIT côté atteint la cible (`rawloader._large_enough(..., fill=True)`) - sinon le recadrage donnerait un carré trop petit, et le RAW est alors dématricé en entier.
  - La galerie HTML n'est pas concernée : sa grille CSS garde les proportions naturelles des photos (infobulle et manuel mis à jour en conséquence).
  - Verrouillé par 17 nouveaux tests (`tests/test_thumbnail.py`, `tests/test_contactsheet.py`), dont un rendu complet de planche en « Entière » vs « Remplir », avec et sans légende ; vérifiés en neutralisant temporairement le câblage (ils échouent bien).
- **Position du titre, position de l'auteur et numérotation des planches : trois réglages du Profil qui n'étaient lus nulle part**, constatés en vérifiant les autres champs du Profil après « Remplir » : `title_position`, `author_position` et `page_numbering` étaient définis, validés et enregistrés dans le JSON, mais aucun code de rendu ne les lisait (le titre et l'auteur étaient toujours centrés, le numéro de planche toujours affiché). Ils sont désormais câblés de bout en bout et réglables dans la section avancée (« Mise en page » : menus « Titre » et « Auteur » - À gauche / Centré / À droite / Masqué - et case « Numéroter les planches »).
  - Planches (donc aussi PDF et aperçu) : le titre puis l'auteur restent l'un SOUS l'autre, chacun aligné selon sa propre position, sur les marges de la page. « Masqué » supprime la ligne et la grille remonte d'autant (le nom du dossier n'est alors plus affiché à la place d'un titre masqué). Un titre ou un auteur trop long pour la largeur utile est d'abord réduit (jusqu'à 28 px pour le titre, 20 px pour l'auteur), puis tronqué par « … » en dernier recours - sans cette garde, un titre long aligné à droite aurait commencé hors de la page. Un texte qui tient déjà garde exactement sa taille d'origine.
  - « Numéroter les planches » décochée : seul le libellé « Planche X/Y » disparaît ; la mention de crédit en bas de page reste toujours affichée.
  - Galerie HTML : le titre et l'auteur de l'en-tête suivent aussi leur position (alignement CSS, ou ligne supprimée si « Masqué » ; le titre de l'onglet du navigateur est conservé). Le compteur d'images et la pagination de la galerie ne changent pas : la numérotation des planches ne concerne que les planches et le PDF.
  - Réglages par défaut (titre et auteur centrés, numérotation cochée) : rendu des planches pixel pour pixel identique, balisage HTML identique, profil par défaut toujours non transmis au CLI.
  - Verrouillé par 22 nouveaux tests (`tests/test_contactsheet.py`, `tests/test_htmlgallery.py`) ; vérifiés en neutralisant temporairement chacun des câblages (ils échouent bien).
- **Les réglages avancés rendaient la fenêtre principale plus haute que l'écran**, signalé par l'utilisateur : dépliée, la section avancée portait la fenêtre d'environ 1060 px à 1610 px de haut et repoussait les boutons « Lancer »/« Quitter » hors de vue. Elle s'ouvre désormais dans une **fenêtre modale à part**, via un bouton « Réglages avancés… » de la fenêtre principale, dont la hauteur ne dépend plus de ces réglages (environ 1075 px, dont 260 px minimum pour le journal de génération).
  - Le contenu de cette fenêtre défile dans sa propre zone (ascenseur), dont la hauteur maximale suit celle de l'écran : sur un écran bas, la barre du bas - message d'état et bouton « Fermer » - reste toujours visible. Fermeture par le bouton, la croix ou la touche Échap.
  - Les réglages sont conservés d'une ouverture à l'autre (la fenêtre est masquée, non détruite) ; ils s'appliquent à la génération et à l'aperçu même si la fenêtre n'a jamais été ouverte (profil par défaut inchangé).
  - Les messages liés à cette fenêtre (aperçu sans dossier choisi, profil enregistré/chargé) s'affichent dans sa barre d'état - le journal de la fenêtre principale étant masqué tant qu'elle est ouverte - en plus du journal. L'aperçu et les sélecteurs de fichier s'ouvrent par-dessus elle.
  - Aucun réglage, aucune valeur par défaut ni sortie ne change ; seules la place et l'ouverture de ces réglages changent. Vérifié sous GTK4 réel (Xvfb) sur un grand et un petit écran (1280×600 : ascenseur actif, bouton « Fermer » visible), dont un aperçu lancé depuis la fenêtre avancée.
- **La fenêtre principale était encore trop haute pour l'écran, et son bas (journal, messages) en sortait**, signalé par l'utilisateur après le déplacement des réglages avancés (elle faisait encore ~1075 px de haut) :
  - Le bouton « Réglages avancés… » est désormais sur la ligne des boutons d'action, juste après « Lancer la génération » (il occupait une ligne à lui seul).
  - Le journal de génération ne réserve plus que 120 px au minimum (260 px auparavant). Il reste extensible : il récupère l'espace gagné quand on agrandit la fenêtre. Hauteur de la fenêtre principale : ~1075 px → ~890 px sur un grand écran.
  - Sur un petit écran, le formulaire (titre, dossiers, aperçu des photos, options) défile dans une zone à ascenseur, plafonnée à ce que l'écran peut contenir ; le bas de l'onglet - boutons d'action, progression, journal - reste toujours visible et n'est jamais poussé hors de l'écran. L'ascenseur n'est affiché que si le formulaire défile réellement ; sur un grand écran, rien ne change (aucun ascenseur, fenêtre à la taille de son contenu). Mesuré sous GTK4 réel : fenêtre de 659 px de haut sur un écran de 768 px, 517 px sur un écran de 600 px (contre ~1075 px).
  - Fenêtre des réglages avancés, rendue plus étroite : ~1260 px → ~990 px de large (lignes de réglages recomposées - colonnes/lignes du modèle Libre sous le modèle, titre/auteur/numérotation sur une ligne - et champs de légende sur 4 colonnes au lieu de 6). Auparavant, un écran de 1366 px de large aurait exigé un ascenseur horizontal pour quelques pixels. Aucun réglage n'est modifié.
  - Manuel (×4) : le paragraphe de la fenêtre principale annonçait à tort qu'elle « s'ouvre maximisée par défaut » ; elle s'ouvre à la taille de son contenu (aucune maximisation dans le code). Corrigé et complété.

### Ajouté

- **Thème graphique et légendes personnalisables, désormais aussi dans la galerie HTML** (cahier des charges §1/§4 - après les planches contact JPEG/PDF) : les quatre thèmes (Clair/Sombre/Neutre/Système, couleurs personnalisées éventuelles comprises) et les légendes par photo configurées dans le Profil (`portfolio/presentation/`) s'appliquent désormais également à la galerie HTML générée, via les mêmes réglages que les planches - aucune règle de couleur ou de légende dupliquée entre les deux. Le thème "Système" laisse le NAVIGATEUR du visiteur décider (media query CSS `prefers-color-scheme`, qui réagit même sans régénérer la galerie), et un petit sélecteur discret en pied de page permet en plus à chaque visiteur de basculer lui-même entre clair et sombre dans son propre navigateur, indépendamment du thème choisi pour la galerie - son choix est mémorisé (`localStorage`, propre à son navigateur) et appliqué dès le chargement de la page, sans effet de clignotement. La visionneuse plein écran (lightbox) reste volontairement sombre dans tous les cas, indépendante du thème de la page. Sans aucune légende configurée, la grille de vignettes garde un marquage HTML strictement identique à avant (aucune lecture EXIF superflue). Vérifié avec un vrai Chromium (Playwright) : rendu clair/sombre/neutre, media query système sous préférence claire et sombre, bascule manuelle et persistance après rechargement, légendes effectivement affichées et échappées HTML.
- Galerie HTML : clic sur une vignette ouvre désormais une visionneuse plein écran avec navigation précédent/suivant (flèches ‹ › ou clavier, fermeture par Échap ou clic en dehors), au lieu d'ouvrir chaque image dans un nouvel onglet.
- Visionneuse de la galerie HTML enrichie : indicateur de la page contenant la photo affichée, champ « aller à la page », nom du fichier affiché, bouton de téléchargement, panneau d'informations (résolution réelle d'origine, taille du fichier, date de prise de vue), bascule plein écran (raccourcis clavier `I` et `F` en plus des boutons).
- Visionneuse de la galerie HTML : zoom de 50 % à 200 % par pas de 10 % (boutons +/-, clic sur le pourcentage pour réinitialiser, raccourcis clavier `+`/`-`/`0`), réinitialisé automatiquement à chaque changement de photo.
- Visionneuse de la galerie HTML : navigation photo suivante/précédente à la molette de la souris ; zoom à la molette avec Ctrl, Alt ou Cmd maintenu (sans déclencher le zoom natif du navigateur ni faire défiler la page en arrière-plan).
- **Interface graphique traduite en anglais, allemand et espagnol** (en plus du français), avec un sélecteur de langue dans un dialogue Préférences accessible depuis un nouveau menu (bouton hamburger dans la barre de titre) : Langue système (par défaut, repli sur l'anglais avec avertissement si la langue détectée n'est pas disponible), English, Français, Deutsch, Español. Un changement de langue prend effet au redémarrage de l'application.
- **Le CLI (`portfolio.py`) et la galerie HTML générée sont également traduits** dans les 4 langues : nouvelle option `--language` (résolue avant la construction du parser, pour que `--help` s'affiche déjà dans la bonne langue), tous les messages de progression et d'aide traduits, et l'intégralité de la galerie HTML générée (en-tête, navigation, visionneuse, `<html lang="...">`). L'interface graphique transmet automatiquement sa langue active au sous-processus de génération, pour que la galerie produite corresponde toujours à la langue affichée à l'écran.
- **Le manuel utilisateur est traduit dans les 4 langues** (`docs/planche-contact-manual.{en,de,es}.html`, en plus de la version française existante) : l'onglet Aide ouvre désormais la version correspondant à la langue active de l'application, avec repli sur le français si le fichier de cette langue est absent. L'internationalisation du projet est ainsi complète — interface graphique, CLI, galerie HTML générée et manuel.
- Galerie HTML : ajout d'une mention développeur/licence (« Développé par Gilles MAGNEVILLE, sous licence GNU GPL v3 », traduite dans les 4 langues) sous « Galerie générée par Planche-Contact » en pied de chaque page.
- « Afficher les résultats » est désormais opérant sur des résultats déjà présents dans le dossier de sortie (planches, PDF, galerie HTML, index CSV d'une session précédente), sans obliger à relancer une génération pour les rouvrir : vérifié au changement du champ dossier de sortie et au démarrage si un dossier était mémorisé. La génération reste bien sûr toujours possible si souhaitée.

### Modifié

- Statut du portage Windows mis à jour : validé sur machine réelle, sans bug apparent, publié comme release officielle (`README.md`, `windows/README.md`, `PROJECT_CONTEXT.md`).
- Sélecteur de langue déplacé de l'onglet À propos vers un nouveau dialogue Préférences, accessible par un menu (bouton hamburger dans la barre de titre) : l'onglet À propos redevient purement informatif, un réglage n'ayant logiquement rien à y faire.

### Corrigé

- Récursivité sous Windows : les images déjà générées lors d'une exécution précédente (`planches/`, `gallery/`) pouvaient être re-détectées comme photos sources (ex : 185 images comptées pour 60 réelles), l'exclusion basée sur une comparaison textuelle des chemins (`Path.resolve()` + `relative_to()`) échouant lorsqu'un même dossier physique est atteint par deux chemins textuellement différents — cas typique d'un lecteur réseau mappé vs son équivalent en chemin UNC. Comparaison désormais basée sur l'identité réelle du fichier (`os.path.samefile()`), bornée au dossier d'entrée pour éviter un appel système par niveau jusqu'à la racine du système de fichiers sur chaque photo (sensible sur un partage réseau).
- Galerie HTML : filigrane parfois tronqué en bas des vignettes (mosaïque à taille de police fixe appliquée séparément sur un canevas ~6x plus petit que l'image pleine taille, produisant un motif disproportionné selon la hauteur exacte de chaque photo). La vignette est désormais dérivée par simple redimensionnement de l'image pleine taille déjà filigranée, garantissant un rendu identique (juste réduit).
- Barre de progression de l'interface graphique : dépendait en partie d'une ligne de texte en français (« Planche X/Y ») imprimée par le CLI, ce qui l'aurait cassée dans toute autre langue. Retirée avant de traduire le CLI — redondante de toute façon avec le marqueur `PROGRESS:X/100` (jamais traduit) qui suit immédiatement chaque planche générée.
- **Régression** : les boutons « Choisir... » (dossiers d'entrée et de sortie) n'ouvraient plus le sélecteur de dossier, sans aucun message d'erreur visible. Cause : `_choose_folder()` utilisait `_` comme variable jetable (`uri, _, label = line.partition(" ")`, lecture des signets GTK) dans la même méthode qui appelle par ailleurs `_("...")` pour traduire le titre du dialogue — Python traite alors `_` comme local à toute la fonction, provoquant un `UnboundLocalError` à chaque clic, silencieusement avalé par PyGObject. Variable renommée en `_sep` ; vérifié qu'aucune autre fonction du fichier ne cumule les deux usages (analyse AST systématique, pas seulement celle qui posait problème).
- Visionneuse de la galerie HTML : les flèches précédent/suivant (et la molette, et le clavier) bouclaient sur les seules photos de la page en cours au lieu de passer réellement à la photo suivante/précédente lorsqu'elle se trouve sur une autre page. La navigation franchit désormais les pages (avec bouclage sur l'ensemble de la galerie aux deux extrémités), en ouvrant automatiquement la bonne photo à l'arrivée sur la page suivante/précédente, avec un message d'avertissement (traduit dans les 4 langues) lorsque ce franchissement boucle sur l'ensemble de la galerie plutôt qu'un simple changement de page.
- Changer de langue dans l'onglet À propos sans redémarrer l'application ne mettait pas à jour la langue réellement transmise au sous-processus de génération (`self._language` restait bloquée sur la langue de démarrage, malgré la préférence sauvegardée correctement) : une génération lancée aussitôt après un changement de langue repartait avec l'ancienne langue. Détecté en testant explicitement ce scénario.
- Visionneuse de la galerie HTML : le bouton de téléchargement ouvrait l'image dans l'onglet en cours (ou un nouvel onglet) au lieu de déclencher la boîte de dialogue d'enregistrement du navigateur. Corrigé en passant par un `Blob` (`fetch()` + `URL.createObjectURL()`) plutôt que le simple attribut HTML `download`, peu fiable une fois servi via HTTP(S) selon les navigateurs — vérifié avec un vrai Chromium (Playwright), téléchargement effectif et fichier de taille identique à l'original. **Limite restante, non contournable** : si la galerie est ouverte directement en `file://` (double-clic sur `index.html`), Firefox et Chrome bloquent de façon identique toute solution JavaScript (`fetch`, `XMLHttpRequest`, lecture d'un `<canvas>`) pour accéder à un fichier voisin, depuis un correctif de sécurité largement adopté (CVE-2019-11730) — un message explicatif s'affiche alors, invitant à un clic droit « Enregistrer l'image sous » ou à consulter la galerie via un serveur web pour un téléchargement en un clic.
- Visionneuse de la galerie HTML : une fois l'image zoomée, la barre du haut (nom du fichier, actions) disparaissait derrière elle au lieu de rester visible au premier plan (`transform: scale()` fait de l'image un élément "positionné" qui se met alors à primer sur les barres fixes selon l'ordre du DOM) ; le défilement pour se déplacer dans l'image agrandie ne fonctionnait pas et affectait la page en arrière-plan à la place (chaînage de défilement par défaut d'un conteneur qui n'a lui-même rien à défiler). Corrigé en donnant un `z-index` explicite à chaque barre/bouton de la visionneuse, en ajoutant `overscroll-behavior: contain`, et en remplaçant le zoom par de vraies largeur/hauteur en pixels (`transform` ne change que le rendu visuel, jamais la taille de mise en page prise en compte par le défilement) — les trois vérifiés avec un vrai Chromium (Playwright).
- Tri par date EXIF (photos JPEG/PNG, non RAW) : `DateTimeOriginal`/`DateTimeDigitized` n'étaient en réalité jamais lus (ces tags vivent dans un sous-IFD Exif séparé, inaccessible via `Image.getexif().get()` direct), le tri retombait donc silencieusement sur la date de modification du fichier depuis le début. Découvert en ajoutant l'affichage de la date dans la nouvelle visionneuse, qui l'a rendu visible.
- Visionneuse de la galerie HTML : une fois zoomée, l'image apparaissait plaquée en haut-à-gauche au lieu de rester centrée, et ne pouvait pas être déplacée à la souris ou au tactile pour en examiner les autres parties (seule la molette fonctionnait, via le défilement natif du conteneur). Cause : l'approche précédente (voir plus haut) basculait le centrage en haut-à-gauche dès le zoom activé pour rendre le débordement atteignable au défilement, au prix du centrage et de tout geste de glisser-déposer. Remplacée par une approche différente : l'image reste toujours centrée, et un vrai glisser-déposer (souris/tactile/stylet via les Pointer Events) déplace son rendu (`transform: translate()`), borné pour ne jamais pouvoir en sortir complètement l'image — la molette, quand zoomée, déplace désormais l'image de la même façon plutôt que de s'appuyer sur un défilement natif qui n'existe plus. Vérifié avec un vrai Chromium (Playwright) : centrage à 200 %, glissement au delta exact de la souris, bornage aux quatre coins, remise à zéro au retour à 100 % ou au changement de photo.
- Planches contact : les vignettes de la dernière ligne pouvaient légèrement déborder du bas physique de la planche pour certaines combinaisons nombre d'images par planche / format de page (cas découvert : 24 images en A4, où l'ancien calcul produisait des vignettes de 505 px débordant d'environ 139 px du bas de la planche). Cause : `create_contact_sheet()` ne retranchait l'espacement entre vignettes (5 mm) que de la largeur disponible pour déterminer la taille finale des vignettes, jamais de la hauteur, alors que ce même espacement s'ajoute pourtant réellement entre les lignes lors du placement final. Sur les 55 combinaisons couvertes par les réglages proposés dans l'interface graphique (5 formats de page × 11 valeurs de « photos par planche » de 8 à 48 par pas de 4), 27 étaient affectées ; une fois corrigées, leurs vignettes sont environ 5 à 15 % plus petites qu'avant selon les cas, tandis que le réglage par défaut (A4, 12 photos par planche) n'était pas concerné et reste inchangé. Nouveaux tests de non-régression (`tests/test_contactsheet.py`) couvrant l'ensemble de ces combinaisons ainsi qu'une génération réelle de bout en bout sur le cas ayant révélé le bug.

## [1.5.3] - 2026-08-03

### Ajouté

- Procédure de contournement de l'avertissement SmartScreen Windows à l'installation, documentée pour l'utilisateur final (`windows/README.md`, `README.md`, manuel utilisateur).
- Mention transparente de l'assistance de Claude.ai (Anthropic) à la conception du logiciel, dans le `README.md`, le manuel utilisateur et l'onglet « À propos » de l'application.

## [1.5.1] - 2026-08-03

### Ajouté

- Manuel utilisateur : note sur le respect automatique de l'orientation EXIF, mention que l'onglet Aide ouvre ce manuel, exemple CLI avec `--html-per-page`.

### Retiré

- Traces de diagnostic devenues inutiles : lignes `[DIAG]` dans `FolderPreviewController` (`planche-contact-gtk.py`) et fenêtre console de l'exécutable Windows (`console=True` dans `windows/planche-contact.spec`, repassé à `False`).

## [1.5.0] - 2026-08-02

Consolide l'ensemble des évolutions depuis la 1.2.2-rc.1 (portage Windows,
sélecteur de dossier personnalisé, filigrane unifié, RAW, curseur d'images
par page HTML, métadonnées AppStream, et tous les correctifs associés).

### Ajouté

- Prise en charge des fichiers RAW (`.cr2`, `.cr3`, `.nef`, `.dng`, `.arw`), via `rawpy` — installé et embarqué automatiquement dans le `.deb`, sans étape manuelle.
- Sélecteur de dossier personnalisé (entrée/sortie), en remplacement de la boîte de dialogue native : n'affiche que les dossiers, aperçu de 20 vignettes (2 lignes) sur le dossier survolé, fil d'Ariane cliquable, signets système repris dans la barre latérale.
- Bande d'aperçu du dossier d'entrée dans la fenêtre principale, paginée par lots de 10, avec navigation numérotée.
- Bouton "Afficher les résultats" (planches, PDF, galerie HTML, index CSV) ouvrant chaque élément avec l'application par défaut du système, avec message clair si aucune application n'est disponible pour le type de fichier concerné.
- Curseur d'opacité du filigrane dans l'interface (0-100 %, défaut 40 %), ainsi que l'argument `--watermark-opacity` en ligne de commande.
- En-tête des planches : nom du dossier source affiché par défaut quand aucun des champs Titre/Auteur/Filigrane n'est renseigné.
- Onglet "À propos" : mention de la licence GNU GPL v3, nom du développeur et lien vers le dépôt GitHub.
- Portage Windows 10/11 (`windows/`) : script de build PowerShell, fichier `.spec` PyInstaller, installeur NSIS, à partir du même code source que la version Linux (le moteur `portfolio/` est strictement identique ; l'interface graphique ne reçoit que quelques ajouts ciblés et sans effet sous Linux/macOS : bloc de démarrage indiquant à GTK4 où trouver ses bibliothèques embarquées, et repli sur `os.startfile` pour ouvrir un fichier avec l'application par défaut du système).
- Documentation utilisateur entièrement réécrite (`docs/planche-contact-manual.html`) et guide de build Windows dédié (`windows/README.md`).
- Curseur "Images par page" pour la galerie HTML dans l'interface (12 à 64 par pas de 4, sur la même ligne que la case "Générer Galerie HTML"), ainsi que l'argument `--html-per-page` en ligne de commande.
- Métadonnées AppStream (`metainfo/planche-contact.metainfo.xml`), installées dans `/usr/share/metainfo/` : permet à App Center (PackageKit + AppStream, depuis Ubuntu 26.04) de reconnaître pleinement le paquet.

### Modifié

- Filigrane unifié : un seul rendu (mosaïque, orientation, opacité) utilisé de façon strictement identique sur les planches, le PDF et la galerie HTML (auparavant, trois implémentations différentes coexistaient, avec un rendu visiblement différent selon la sortie).
- Filigrane par défaut plus discret : taille réduite (~30 %) et opacité réduite (70 % → 40 %).
- Fenêtre principale : ouverture à sa taille minimale naturelle plutôt qu'une taille fixe imposée, tout en restant redimensionnable.
- Regroupement de champs pour réduire la hauteur du formulaire : Titre du projet et Nom de l'auteur sur une même ligne ; Images par planche, Format de la planche, Filigrane et Orientation sur une même ligne.
- Champs Titre du projet, Nom de l'auteur, Dossier d'entrée et Dossier de sortie : largeur fixe et raisonnable au lieu de s'étirer sur toute la largeur de la fenêtre.
- Marge haute des planches contact et du PDF réduite, espace entre l'en-tête et la grille de vignettes agrandi.
- Chargement des polices rendu multiplateforme (Linux/Windows/macOS) au lieu d'un chemin Linux codé en dur.
- Nom du projet uniformisé en "Planche-Contact" (au lieu de "Planche-Contact Linux") dans le README et ce journal, le projet n'étant plus limité à Linux.
- Bouton "Planches contact" du menu "Afficher les résultats" : ouvre désormais le dossier `planches/` (gestionnaire de fichiers) plutôt qu'une image individuelle — comportement identique quel que soit le nombre de planches générées.

### Corrigé

- Dossier de sortie non créé automatiquement avant la génération, provoquant une erreur si le dossier n'existait pas encore.
- Permissions des fichiers embarqués dans le `.deb` dépendantes du `umask` de la machine de build, pouvant rendre l'application illisible pour un utilisateur normal une fois installée.
- Icône de l'application absente du `.deb` (le script cherchait un fichier à un chemin inexistant) ; installée désormais en plusieurs tailles (48 à 256 px).
- Fichier `VERSION` du projet pouvant être incrémenté même en cas d'échec de build, désynchronisant le numéro de version affiché du contenu réellement publié.
- Fenêtre principale agrandie de ~90 px juste après son affichage (le temps que l'aperçu du dossier d'entrée se charge), empêchant un centrage vertical correct par le gestionnaire de fenêtres à l'ouverture.
- Police embarquée non appliquée sur les planches contact ni le PDF (fonctionnait uniquement pour la galerie HTML) : l'en-tête et le pied de page des planches chargeaient un chemin de police codé en dur au lieu de passer par `utils.get_font()`.
- Galerie HTML : orientation EXIF non respectée, toutes les photos affichées en paysage à la taille du capteur quel que soit leur cadrage réel — `ImageOps.exif_transpose()` n'était plus appelé depuis le passage au décodage unique (image pleine taille + vignette).
- `.deb` : les scripts `postinst`/`postrm` n'étaient en réalité jamais exécutés par dpkg (ils atterrissaient comme simples fichiers de données inertes à `/DEBIAN/`, `fpm` ne reconnaissant pas ce dossier comme `dpkg-deb --build` natif le ferait) — aucune vérification de l'environnement Python embarqué n'avait donc jamais lieu à l'installation.
- `.deb` : venv embarqué pouvant être incomplet (ex : `reportlab` manquant) selon ce qui se trouvait déjà installé au niveau système sur la machine de build, `pip install` sautant silencieusement la copie locale dans un venv `--system-site-packages` sans `--ignore-installed`.
- Windows : taille de l'application non affichée dans *Paramètres > Applications > Applications installées* — `IntFmt $0 "0xX" $0` (syntaxe NSIS 2.x non fonctionnelle en NSIS 3.x) ne convertissait pas la taille calculée en hexadécimal, `EstimatedSize` retombait systématiquement à 0.

### Performances

- Décodage des vignettes et planches nettement accéléré : préférence donnée à l'aperçu JPEG déjà embarqué dans les fichiers RAW plutôt qu'un dématriçage complet, et décodage "draft" accéléré pour les sources JPEG.
- Galerie HTML : fusion de deux passes de décodage redondantes en une seule (vignette dérivée de l'image déjà décodée, plus besoin de redécoder la source deux fois), génération pleinement parallélisée.
- Plafond de processus parallèles relevé (8 → 64), pour mieux exploiter les machines à nombreux cœurs.
- Mise en cache du chargement des polices du filigrane, rechargées depuis le disque à chaque appel auparavant.

---

## [1.2.2-rc.1] - 2026-07-23

### Première Release Candidate publique

#### Fonctionnalités

- Génération de planches contact photographiques haute qualité (300 dpi).
- Interface graphique GTK 4.
- Génération d'un document PDF.
- Génération d'une galerie HTML responsive.
- Génération d'un index CSV.
- Prise en charge des images JPEG ainsi que de nombreux formats RAW.

#### Points forts

- Fonctionnement sans base de données.
- Traitement direct des dossiers d'images.
- Interface graphique simple et rapide.
- Logiciel libre distribué sous licence GPL-3.0.

---

## [1.2.1] - 2026-07-22

- Modification de l'onglet "À propos" et amélioration de `build-deb.sh`.
- Correction du numéro de version affiché dans le `.deb` et dans l'onglet "À propos".

## [1.2.0] - 2026-07-22

- Nettoyage des champs de l'interface, correction de l'orientation du filigrane, ajout du symbole copyright au filigrane.

## [1.1.20] - 2026-07-22

- Changement du nombre d'images par planche, ajout d'une mention en bas de page sur les planches, correction de l'orientation du filigrane, amélioration du script de build.

## [1.1.17] - 2026-07-22

- Effacement de la galerie avant une nouvelle génération.

## [1.1.16] - 2026-07-22

- Optimisation de la génération de la galerie et de la navigation.

## [1.1.11] - 2026-07-22

- Précision dans la description.
- Amélioration des indicateurs de progression.

## [1.1.10] - 2026-07-17

- Amélioration de la galerie : filigrane, format des photos, mise en page.

## [1.1.8] - 2026-07-16

- Optimisation du filigrane de la galerie.

## [1.1.5] - 2026-07-16

- Correctif sur la galerie.

## [1.1.3] - 2026-07-16

- Optimisation de la création de la galerie et nouveau script `build-deb.sh`.

## [1.1.2] - 2026-07-16

- Premier import du projet sous sa forme actuelle.

## [1.0.1] - 2026-07-15

### Version initiale publique

- Ajout de l'interface graphique GTK4.
- Ajout de l'export PDF et HTML.
- Packaging Debian amélioré.
