# Veille TLS

Journal de veille quotidien sur la télésurveillance et la sécurité privée.

Chaque matin, GitHub lance automatiquement un programme qui :

1. **collecte** les publications récentes (Google Actualités, flux RSS, pages surveillées) ;
2. **dédoublonne** et **préfiltre** par mots-clés, sans coût ;
3. **analyse** chaque article avec une IA qui le classe, le résume, lui donne un score de pertinence de 0 à 100, explique ce score, propose une action pour les articles importants et repère les échéances ;
4. **publie** le journal sur un site public : canaux par catégorie, recherche, lu / non lu, favoris, **résumé de la semaine** (synthèse rédigée par l'IA, 10 articles à retenir, échéances à venir ; mis à jour chaque matin, bilan figé le lundi suivant), archives, calendrier des échéances (abonnable dans un agenda), flux RSS, installable sur téléphone ;
5. **envoie** un e-mail avec les articles notés 70 et plus (si configuré).

Le site est publié à l'adresse indiquée dans `config/site.yaml`.

## Modifier la veille

Tout se règle dans le dossier `config/`, sans toucher au code :

| Fichier | Contenu |
|---|---|
| `config/profil.yaml` | Le lecteur, les six catégories, leurs mots-clés, le barème des scores |
| `config/sources.yaml` | Les recherches Google Actualités, les flux RSS et les pages surveillées |
| `config/site.yaml` | Le titre du site, les mentions légales, le modèle d'IA, le plafond d'articles analysés |

### Apprendre à l'IA ce qui ne vous intéresse pas

Sous chaque article, le bouton **Non pertinent** masque l'article dans votre navigateur. Le lien
**Apprendre à l'IA** qui apparaît alors ouvre un ticket GitHub pré-rempli : il suffit de le valider
(en ajoutant une raison si vous le souhaitez). Le lendemain matin, le passage quotidien lit ces
tickets, les referme, retire l'article du site et ajoute l'exemple aux consignes de l'IA
(`data/avis.json`, 60 derniers avis). Seuls les tickets ouverts par le propriétaire du dépôt sont
pris en compte : un visiteur peut masquer un article chez lui, sans effet sur le journal.

## Mise en service (une seule fois)

1. **Activer le site** : *Settings* → *Pages* → *Build and deployment* → *Source* : **GitHub Actions**.
2. **Ajouter la clé de l'IA** : *Settings* → *Secrets and variables* → *Actions* → *New repository secret*, nom `ANTHROPIC_API_KEY`. Sans cette clé, le journal fonctionne quand même, avec une notation par mots-clés et sans résumé.
3. **E-mail du matin (facultatif)** : ajouter de la même façon les secrets `SMTP_USER` (adresse Gmail d'envoi), `SMTP_PASSWORD` (mot de passe d'application Gmail) et `MAIL_TO` (adresse de réception).
4. **Premier passage** : *Actions* → *Journal quotidien* → *Run workflow*. Le bouton « Scan immédiat » du site mène à cette même page.

## Coût

Hébergement et automatisation gratuits. L'analyse par l'IA (Claude Haiku 5.5) coûte de l'ordre de 1 € par mois pour une centaine d'articles par jour, quel que soit le nombre de lecteurs du site.

## Droits d'auteur

Le journal ne reproduit aucun article : il publie un titre, un résumé rédigé par l'IA avec ses propres mots, la source et un lien. Pour mieux résumer, le programme lit le début des articles, sans jamais l'enregistrer ni le publier, et seulement quand le fichier `robots.txt` du site l'autorise. Les flux Google Actualités sont lus comme le ferait un lecteur de flux RSS, une fois par jour, mais leurs liens ne sont pas suivis automatiquement (le `robots.txt` de Google l'interdit aux robots).

## Pour les développeurs

```bash
pip install -r requirements.txt pytest
python -m pytest -q tests        # tests hors ligne
python -m veille.main            # passage complet (réseau nécessaire)
python -m veille.main --site     # régénère le site à partir de data/
```
