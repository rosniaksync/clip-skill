# GTA Clipper Skill: cole o link de uma live e receba shorts prontos

Cole o link de uma live ou VOD (YouTube, Twitch, Kick...) e o Claude:

1. Baixa o trecho pedido (blocos de 1 hora) e o chat
2. Acha os melhores momentos pelo volume do áudio, pelo chat ("kkkk", "clipa") e pelo movimento da imagem
   (ignora menu e tela parada), **antes de transcrever**
3. Transcreve só os melhores trechos (rápido, mesmo em PC fraco) e lê o texto para escolher os cortes
4. Renderiza cada corte em 1080x1920 com card de gancho (2 linhas) e legenda palavra por palavra
5. Gera o kit de postagem (título, descrição, hashtags)

Dois estilos, cada um com seu template em `templates/`:
- **cam** (vídeo com webcam): webcam em cima (2/5), gameplay embaixo (3/5), card do gancho no meio
  da divisão com a etiqueta do canal e a logo, legenda pequena acima do card.
- **nocam** (sem webcam): fundo desfocado, gameplay com leve zoom no meio, título no topo, legenda embaixo.

Cores, fontes, tamanhos, posições, logo e nome do canal ficam nos templates JSON, nada fixo no código.
Os valores de fluxo (duração dos cortes, recuo, blocos de 1 hora, sinais e pesos) ficam em `config.json`.

## Instalação (uma vez)
1. Python 3.9+ e ffmpeg (`winget install Gyan.FFmpeg` no Windows).
2. `pip install -r requirements.txt` e `python scripts/check_setup.py` (deve dizer "All good").
3. Twitch: para baixar o chat dos VODs rode `python scripts/install_twitch_cli.py` (baixa o
   TwitchDownloaderCLI para `tools/`; não vem no git por ter ~90 MB).

## Uso
Abra o Claude Code e escreva, por exemplo: "quero 2 shorts dessa live <link>, primeira hora".
Dá para pedir também: trocar o gancho de um corte, começar mais cedo, outro card (veja o catálogo),
outra cor.

## O que tem aqui
```
gta-clipper-skill/
├── SKILL.md            instruções que o Claude segue (fluxo completo, regras e decisões)
├── CLAUDE.md
├── config.json         duração, recuo, blocos, sinais e pesos
├── assets/logo.png     logo oficial (Cortes GTA 6); logo_antiga_circulo.png = versão anterior
├── fonts/              Montserrat Black e Poppins ExtraBold (estáticas)
├── templates/          cam.json (ativo), nocam.json, cam_laranja.json (backup)
│   └── opcoes/         8 cards com logo e 8 sem logo (copie um para cam.json para aplicar)
├── references/viral-rules.md
├── catalogo-cards/     imagens com todas as opções de card (com e sem logo)
├── tools/              TwitchDownloaderCLI (instalado por scripts/install_twitch_cli.py)
└── scripts/            download, find_hype, transcribe, make_shorts, check_setup
```
Catálogo visual dos cards: `C:\cortes\cards\` (veja `TODOS_OS_CARDS.png`).

## Dicas
- Neste PC (i5 de 2011, sem GPU) achar os momentos de 1 hora leva ~3,5 min, transcrever os 8 melhores
  trechos alguns minutos, e cada corte renderiza em menos de 1 min. Em PC novo é bem mais rápido.
- No máximo 2 jobs pesados ao mesmo tempo.
- Só corte lives que você possui ou tem permissão para repostar.
