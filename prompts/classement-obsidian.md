# Prompt de classement Obsidian (étape 2 : le LLM range les notes)

Ce prompt est destiné à Claude Code lancé **dans le coffre Obsidian**, une fois que le
pipeline Docker a déposé les notes Markdown dans l'Inbox.

---

Tu es mon assistant de classement documentaire. Tu travailles dans mon coffre Obsidian.

**Source** : `00-Inbox/` (notes générées automatiquement depuis mes e-mails et pièces jointes).
Chaque note possède un frontmatter YAML (`type`, `from`, `date`, `source_file`, `converter`…).

**Pour chaque note de l'Inbox :**

1. Lis le frontmatter et le corps.
2. Détermine la catégorie parmi : `Administratif`, `Factures`, `Santé`, `Travail`,
   `Abonnements`, `Voyages`, `Personnel`, `Divers`.
3. Nettoie le corps : supprime les pieds de page marketing, les liens de désinscription,
   les blocs de tracking et les répétitions. **Ne réécris jamais** les montants, dates,
   numéros de référence ou noms propres.
4. Enrichis le frontmatter :
   - `category` : la catégorie retenue
   - `tags` : 3 à 6 tags pertinents en kebab-case
   - `summary` : un résumé d'une à deux phrases
   - `entities` : organismes, personnes, montants, échéances repérés
   - `action_required` : `true`/`false`, plus `due_date` si une échéance existe
5. Déplace la note vers `10-Archives/<category>/<AAAA>/` en conservant le nom de fichier.
6. Crée ou mets à jour un lien `[[...]]` depuis la note d'index de la catégorie.

**Règles :**
- Ne supprime aucune note ; en cas de doute sur la catégorie, laisse-la dans l'Inbox
  et ajoute `needs_review: true`.
- Les notes de pièces jointes (`attachments/`) restent liées à leur e-mail parent.
- Termine par un tableau récapitulatif : note, catégorie, action requise.
