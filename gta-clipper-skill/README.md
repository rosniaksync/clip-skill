# GTA Clipper Skill: cole o link de uma live e receba shorts prontos

Cole o link de uma live ou VOD (YouTube, Twitch, Kick...) e o Claude:

1. **Baixa o vídeo inteiro em blocos** (até 1080p), sem perguntar nada: o Claude decide se faz blocos de 30 min
   ou de 1 hora (30 min para live no ar, vídeo curto ou muito agitado; 1 hora para VOD longo ou conteúdo calmo). Na Twitch baixa também o chat; no YouTube guarda o mapa de
   "mais repetidos" (heatmap). Mede o início real do trecho (o corte por cópia começa no keyframe anterior).
   Live ainda no ar: na Twitch usa o VOD da live atual; no YouTube baixa só o que já passou.
2. **Detecta o idioma** sozinho (3 a 5 trechos de 30 s do meio do vídeo, modelo tiny) e **transcreve o vídeo
   todo com o tiny** (rápido, só para ler).
3. **Lê tudo em blocos de 10 minutos** procurando piadas, reviravoltas, fails, reações e histórias. Os sinais
   (áudio, chat, "clipa", heatmap, movimento) só ajudam a conferir.
4. **Olha os frames** dos candidatos (pega momentos visuais sem fala).
5. **Retranscreve só os candidatos com o small** (palavras precisas para a legenda).
6. **Renderiza** cada corte em 1080x1920 com card de gancho e legenda palavra por palavra, com **10 s extras
   antes e depois** para o ajuste fino no editor. Vídeo gringo: legenda traduzida para português pelo Claude.
7. **Entrega** o preview, o kit de postagem (título, descrição, hashtags, corte sugerido no arquivo) e
   **registra cada short no Notion** (base "Resultados dos Cortes").

Para trocar o gancho: "corte N: GANCHO / SUBGANCHO" (renderiza só aquele e atualiza a mesma linha do Notion).

## Estilos

Cada um tem seu template em `templates/`:
- **cam** (com webcam): webcam em cima, gameplay embaixo, card RSK CORTES na divisão, legenda acima do card.
- **nocam** (sem webcam): fundo desfocado, logo redonda e gancho em degradê no topo, gameplay no meio, legenda embaixo.

Cores, fontes, tamanhos, posições, logo e nome do canal ficam nos templates. Fluxo, caminhos, pesos dos sinais,
detecção de idioma, extras de 10 s e Notion ficam em `config.json`. Nada fixo no código.

## Instalação (uma vez, ou no PC novo)

1. Python 3.9+, ffmpeg e Node.js (Windows: `winget install Gyan.FFmpeg` e `winget install OpenJS.NodeJS.LTS`).
2. `python -m pip install -r requirements.txt`
3. Gerador do PO token do YouTube (bgutil) e TwitchDownloaderCLI (`python scripts/install_twitch_cli.py`).
4. Ajuste os caminhos em `config.json` → `paths` (cookies, gerador do PO token, pasta de trabalho).
5. `python scripts/check_setup.py` deve dizer "Tudo OK". Se faltar algo, ele mostra o comando exato.
6. Notion: `claude mcp add --transport http --scope user notion https://mcp.notion.com/mcp` e depois `/mcp`.

Cookies e problemas de download do YouTube: veja o `COMO-USAR.md` (caminho em `paths.setup_guide`).

## Uso

Abra o Claude Code e escreva, por exemplo: "quero 2 shorts dessa live <link>, primeira hora".

## O que tem aqui

```
gta-clipper-skill/
├── SKILL.md            instruções que o Claude segue (fluxo completo e decisões)
├── CLAUDE.md
├── config.json         caminhos, duração, extras, blocos, idioma, sinais e pesos, Notion
├── assets/logo.png     logo oficial (RSK CORTES)
├── fonts/              Montserrat Black e Poppins ExtraBold
├── templates/          cam.json e nocam.json
├── references/viral-rules.md   regras de corte
├── tools/              TwitchDownloaderCLI (instalado por scripts/install_twitch_cli.py, fora do git)
└── scripts/
    ├── download.py        baixa (trecho, live, chat da Twitch, heatmap, offset real)
    ├── transcribe.py      detecta o idioma (lang.json) e transcreve (tiny no todo, small nos candidatos)
    ├── read_blocks.py     lê a transcrição em blocos de 10 min
    ├── find_hype.py       sinais de apoio (áudio, chat, "clipa", heatmap, movimento)
    ├── extract_frames.py  folhas de frames dos candidatos
    ├── make_shorts.py     render (±10 s, legenda traduzida), preview, kit, renders.json
    ├── check_setup.py     confere a instalação
    ├── install_twitch_cli.py
    └── common.py          leitura do config.json e utilidades
```

## Dicas

- No máximo 2 jobs pesados ao mesmo tempo (transcrição/render). Download pode rodar junto.
- Só corte lives que você possui ou tem permissão para repostar.
