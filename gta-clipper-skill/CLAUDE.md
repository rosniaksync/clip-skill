# Live -> Shorts virais

Esta pasta é uma skill do Claude. Quando o usuário colar o link de uma live/vídeo ou pedir
shorts/cortes/reels (ex.: "quero 2 shorts dessa live <link>"), siga o `SKILL.md` desta pasta.

- Fluxo (21/11/2026): sem perguntas, blocos de 1 h → download leve → small no bloco todo + varredura de quadros juntos →
  leitura → frames dos candidatos → conferir início/fim (`check_cut.py`) → trechos em alta → render → Notion. Máximo de shorts.
- Scripts em `scripts/`, trabalho em `work/<id>/`, shorts em `work/<id>/shorts/`.
- Tudo ajustável em `config.json` (caminhos inclusive) e `templates/`. Regras de corte em `references/viral-rules.md`.
- Visual aprovado: não mexer em `templates/cam.json`, `templates/nocam.json`, `fonts/`, `assets/logo.png` sem pedido.
