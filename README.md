```markdown
# Planche-Contact

**Planche-Contact** est un outil léger, rapide et sans base de données permettant de générer des **planches contact photographiques** de haute qualité (300 dpi) à partir d’un dossier d’images.

Il propose deux interfaces :

- Une **interface graphique moderne** (GTK4)
- Une **interface en ligne de commande** puissante et scriptable

---

## ✨ Fonctionnalités principales

- Génération de planches contact en **haute résolution** (300 dpi)
- **Taille des vignettes cohérente** sur toutes les pages (y compris la dernière)
- **Filigrane répété** sur l’ensemble des images, sans fond et avec orientation configurable :
  - Horizontal
  - Diagonale horaire
  - Diagonale anti-horaire
- Affichage du **titre du projet** et du **nom de l’auteur** en haut des planches
- Exports multiples :
  - **PDF** complet
  - **Galerie HTML** paginée (auto-contenue)
  - **Index CSV**
- Recherche récursive des images
- Interface graphique intuitive avec suivi de progression en temps réel
- Ligne de commande complète et adaptée à l’automatisation

---

## 📦 Installation

### Prérequis

- Python 3.11 ou supérieur
- PyGObject + GTK4
- Pillow
- ReportLab (pour l’export PDF)

### Installation sous Ubuntu / Debian / Linux Mint

```bash
sudo apt update
sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0
pip install Pillow reportlab
```

### Installation sous Fedora

```bash
sudo dnf install python3-gobject gtk4
pip install Pillow reportlab
```

### Installation sous Arch Linux

```bash
sudo pacman -S python-gobject gtk4
pip install Pillow reportlab
```

---

## 🚀 Utilisation

### Interface Graphique

```bash
python3 planche-contact-gtk.py
```

### Ligne de Commande

```bash
python3 portfolio/portfolio.py -i <dossier_source> [OPTIONS]
```

#### Options principales

| Option                          | Description                                      | Exemple                                      |
|--------------------------------|--------------------------------------------------|----------------------------------------------|
| `-i, --input`                  | Dossier source (obligatoire)                     | `-i /Photos/Voyage`                          |
| `-o, --output`                 | Dossier de sortie                                | `-o ./Resultats`                             |
| `-n, --num`                    | Nombre d’images par planche                      | `-n 16`                                      |
| `--format`                     | Format de page                                   | `--format A3`                                |
| `--title`                      | Titre du projet                                  | `--title "Voyage Islande 2025"`              |
| `--author`                     | Nom de l’auteur                                  | `--author "Abel GEZ"`                        |
| `--watermark`                  | Texte du filigrane                               | `--watermark "© Abel GEZ"`                   |
| `--watermark-orientation`      | Orientation du filigrane                         | `--watermark-orientation "Diagonale horaire"`|
| `--pdf`                        | Générer un PDF                                   | `--pdf`                                      |
| `--html`                       | Générer une galerie HTML                         | `--html`                                     |
| `--csv`                        | Générer un index CSV                             | `--csv`                                      |
| `-r, --recursive`              | Analyse récursive                                | `-r`                                         |

---

## 📌 Exemples

```bash
# Génération simple
python3 portfolio/portfolio.py -i /Photos/2025 --pdf --html

# Version complète avec filigrane diagonal
python3 portfolio/portfolio.py \
  -i /Photos/Islande2025 \
  -n 16 \
  --format A3 \
  --title "Islande 2025" \
  --author "Abel GEZ" \
  --watermark "© Abel GEZ" \
  --watermark-orientation "Diagonale horaire" \
  --pdf --html --csv
```

---

## 🖼️ Captures d’écran

### Interface Graphique

![Interface Graphique](docs/screenshots/gtk-interface.png)

### Exemple de planche contact générée

![Exemple de planche](docs/screenshots/planche-contact-example.jpg)

### Galerie HTML générée

![Galerie HTML](docs/screenshots/html-gallery.png)

> **Note** : Les captures d’écran sont disponibles dans le dossier `docs/screenshots/`.

---

## 📁 Structure du projet

```
portfolio/
├── planche-contact-gtk.py          # Application graphique GTK4
├── portfolio/                      # Package Python
│   ├── config.py
│   ├── contactsheet.py
│   ├── portfolio.py                # CLI principale
│   ├── scanner.py
│   ├── thumbnail.py
│   └── ...
├── docs/
│   ├── planche-contact-manual.html
│   └── screenshots/                # Captures d’écran
└── README.md
```

---

## 📖 Documentation

Un manuel complet et détaillé (style « man page ») est disponible ici :

→ **`docs/planche-contact-manual.html`**

Ce document couvre :
- Tous les champs de l’interface graphique
- La liste exhaustive des options de la ligne de commande
- Des exemples concrets
- Des conseils d’utilisation avancés

---

## 📝 Changelog

### Version actuelle (Juillet 2026)

- **Amélioration majeure du filigrane** : maintenant répété sur toute l’image, sans fond, avec choix d’orientation (Horizontal / Diagonale horaire / Diagonale anti-horaire)
- **Taille des vignettes cohérente** sur toutes les pages grâce à un calcul global basé sur `num_per_sheet`
- Suppression définitive du mode Review (non maintenu)
- Ajout du champ **Nom de l’auteur** dans l’interface graphique
- Amélioration significative de la documentation (manuel complet externe)
- Meilleure gestion des erreurs et des logs
- Ajout de la fonction filigrane qui ne fonctionnait pas sur la galerie html

### Versions précédentes

- Refonte du système de filigrane (suppression du fond noir)
- Uniformisation de la taille des vignettes entre les pages
- Ajout de l’export CSV
- Améliorations de l’interface GTK (meilleure gestion des dossiers récents)

---

## 💡 Conseils d’utilisation

- Pour un rendu homogène, conservez toujours le même nombre d’images par planche.
- Le filigrane en **diagonale** est généralement plus discret et professionnel.
- La galerie HTML est **auto-contenue** : vous pouvez la copier ou l’envoyer sans rien casser.
- Il est recommandé de générer à la fois le **PDF** et la **galerie HTML**.

---

## 🛠️ Développement

Ce projet est conçu pour être simple à maintenir. Les suggestions et contributions sont les bienvenues.

---

## 📄 Licence

Ce projet est distribué sous licence **MIT**.

---

## 👤 Auteur

Gilles MAGNEVILLE

Développé pour un usage personnel et professionnel en photographie.

---

**Planche-Contact** — Des planches contact propres, rapides et sans prise de tête.
```
