# Live -> Shorts virais

Esta pasta é uma skill do Claude. Quando o usuário colar o link de uma live/vídeo ou pedir
shorts/cortes/reels (ex.: "quero 2 shorts dessa live <link>"), siga o `SKILL.md` desta pasta.

- Fluxo: tiny no vídeo todo (idioma detectado sozinho) → leitura em blocos de 10 min → frames →
  small nos candidatos → conferir início/fim (`check_cut.py`) → render no corte exato → registro no Notion.
- Scripts em `scripts/`, trabalho em `work/<id>/`, shorts em `work/<id>/shorts/`.
- Tudo ajustável em `config.json` (caminhos inclusive) e `templates/`. Regras de corte em `references/viral-rules.md`.
- Visual aprovado: não mexer em `templates/cam.json`, `templates/nocam.json`, `fonts/`, `assets/logo.png` sem pedido.
