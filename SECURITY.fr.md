# Politique de sécurité

🇬🇧 [English version](SECURITY.md)

Planche-Contact est maintenu par une seule personne, à titre bénévole. Cette page explique comment signaler un problème de sécurité et ce que vous pouvez en attendre.

## Versions prises en charge

Seule la **dernière version publiée** reçoit les correctifs de sécurité. Si vous utilisez une version plus ancienne, mettez-la d'abord à jour : les versions sont sur la page des [Releases](https://github.com/gillesmagneville/planche-contact/releases) et les changements sont listés dans le [CHANGELOG](CHANGELOG.fr.md).

## Signaler une vulnérabilité

**Merci de ne pas signaler une vulnérabilité dans une Issue, une Pull Request ou une discussion publique** : n'importe qui pourrait la lire avant qu'un correctif existe.

Signalez-la en privé, de l'une de ces deux façons :

1. **Sur GitHub** : ouvrez l'[onglet Security](https://github.com/gillesmagneville/planche-contact/security) du dépôt et cliquez sur **Report a vulnerability**. Seuls vous et le mainteneur voyez le signalement.
2. **Par courriel** : écrivez à [gilles@magneville.fr](mailto:gilles@magneville.fr) avec l'objet « Planche-Contact sécurité ».

Indiquez, autant que possible :

- la version de Planche-Contact (affichée dans la fenêtre « À propos ») et la façon dont vous l'avez installé (paquet `.deb`, AppImage, installeur ou version portable Windows, ou depuis le code source) ;
- votre système d'exploitation ;
- la description du problème et les étapes pour le reproduire ;
- l'impact que vous lui voyez ;
- si le problème vient d'un fichier particulier, ce fichier — seulement si vous avez le droit de le partager.

## Ce que vous pouvez attendre

Ce sont des objectifs, pas des garanties, puisqu'il n'y a qu'un seul mainteneur :

- un accusé de réception de votre signalement sous **7 jours** ;
- une réponse indiquant s'il est considéré comme une vulnérabilité, puis des nouvelles au moins toutes les quelques semaines jusqu'à ce que le sujet soit réglé ;
- un correctif publié dans une **nouvelle version**, mentionné dans le CHANGELOG ; pour un problème grave, un avis de sécurité GitHub également ;
- vous êtes cité dans les notes de version, sauf si vous préférez rester anonyme.

Merci de garder les détails confidentiels jusqu'à la publication d'une version corrigée, pour que les utilisateurs aient le temps de mettre à jour.

## Ce qui est concerné

Planche-Contact travaille sur votre ordinateur, sur vos propres photos, et ne les envoie nulle part. Un signalement est pertinent, par exemple, si :

- une image ou un fichier RAW, ou un profil de réglages (fichier JSON), fait exécuter du code au programme ou lui fait lire ou écrire des fichiers qu'il ne devrait pas ;
- une galerie HTML générée exécute du code provenant des noms de fichiers ou des métadonnées des photos ;
- le paquet `.deb` ou son script d'installation, l'AppImage, l'installeur Windows ou les scripts de construction peuvent être détournés ;
- un fichier d'une version publiée ne correspond pas à son empreinte `.sha256` publiée.

## Ce qui n'est pas concerné

- Une vulnérabilité dans un **composant développé par quelqu'un d'autre** (Pillow, ReportLab, rawpy/LibRaw, GTK, Python…) : merci de la signaler à ce projet. Dites-moi en revanche si la version livrée avec Planche-Contact est touchée, pour que je la mette à jour.
- Les problèmes qui supposent un ordinateur déjà compromis, ou un accès physique à celui-ci.
- Les bugs ordinaires sans conséquence pour la sécurité : ouvrez plutôt une [Issue](https://github.com/gillesmagneville/planche-contact/issues).

## Vérifier ce que vous téléchargez

Téléchargez Planche-Contact uniquement depuis la page des [Releases](https://github.com/gillesmagneville/planche-contact/releases) de ce dépôt. Chaque fichier est publié avec son empreinte `.sha256`, également donnée dans le [README](README.fr.md). L'installeur Windows n'est pas signé numériquement (voir le README) : cette vérification n'en est que plus utile.
