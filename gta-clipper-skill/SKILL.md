---
name: gta-clipper-skill
description: Transforma qualquer live ou vídeo longo (YouTube, Twitch VOD, Kick etc.) em shorts verticais prontos para postar (1080x1920, card de gancho, legenda palavra por palavra, início e fim exatos, pronto para postar sem editar). Use quando o usuário colar um link de live/vídeo e pedir shorts, cortes, reels ou clips.
---

# Live → Shorts virais

O usuário cola o link de uma live. Você baixa, detecta o idioma, transcreve (tiny no vídeo todo), lê tudo em
blocos de 10 min, olha os frames, retranscreve os candidatos com o small, escolhe os cortes, renderiza cada um
como short 1080x1920 (card de gancho, legenda palavra por palavra, começando e terminando no ponto exato) e
registra cada short no Notion.

- Trabalhe em `work/<id>/` dentro de `paths.work_root` do `config.json`; os shorts saem em `work/<id>/shorts/`.
- Scripts em `scripts/` desta skill: `python <skill-dir>/scripts/<nome>.py`.
- Responda em português do Brasil, com atualizações curtas. Mensagens de progresso em português.
- No Windows, rode Python com `PYTHONIOENCODING=utf-8`. Não use `python -I` (esconde pacotes e o `common.py`).

## Configuração (tudo em `config.json` e `templates/`, nada fixo no código)

- **Caminhos** (`paths`): `work_root`, `cookies_master`, `pot_script` (gerador do PO token), `twitch_cli`,
  `setup_guide`. Variáveis de ambiente sobrescrevem: `YT_COOKIES_MASTER`, `BGUTIL_POT_SCRIPT`,
  `TWITCH_DOWNLOADER_CLI`, `CORTES_WORK_ROOT`.
- **Duração do corte:** mínimo `clip_min_seconds` (20), ideal `clip_target_seconds` (25–45), sem máximo
  (`clip_max_seconds` null). Sem enrolação no fim.
- **Corte exato, pronto para postar:** `pad_before` / `pad_after` = 0. O short sai exatamente de `start` a `end`
  do `clips.json`, que você escolhe pelas regras de "Início e fim perfeitos" (`references/viral-rules.md`) e
  confere com `check_cut.py` (passo 4d). O "corte sugerido no arquivo" é o arquivo inteiro (ex.: 0:00 a 0:28).
- **Com folga (só quando o usuário pedir "esse com folga"):** ponha `"folga": true` no corte e renderize só ele;
  o arquivo ganha `pad_folga` (10 s) antes e depois, e o kit mostra onde o corte fica (ex.: 0:10 a 0:38).
- **Recuo antes do pico:** `pre_roll_seconds` (15 s): a reação vem depois do fato. Depois apare para a primeira
  frase/ação forte (gancho primeiro).
- **Sempre o vídeo inteiro. Curto = um bloco só; longo = blocos de 30 min (nunca 60).** Nunca pergunte qual
  trecho nem o tamanho do bloco.
  - **Até 1 hora** (`single_block_max_minutes` = 60; vale para vídeo de 40 min, de 50 min e para live que ainda
    não passou de 1 h): **um bloco só**, baixado inteiro (sem `--section`), sem dividir.
  - **Mais de 1 hora** (vídeo ou live): divide em blocos de 30 min (B = 30, `chunk_minutes`), como abaixo.
  - Live no ar: conta o que já passou. Se tem 45 min, é um bloco só; quando o usuário mandar o link de novo
    e já passar de 1 h, o histórico continua de onde parou e daí em diante vai em blocos de 30 min.
  O bloco N (só quando passar de 1 h) vai de (N−1)·30 menos 5 min (`chunk_overlap_minutes`) até N·30, via `download.py --section` (o bloco 1
  começa em 0:00 e o último termina no fim do vídeo): 00:00:00-00:30:00, 00:25:00-01:00:00,
  00:55:00-01:30:00… Descarte cortes repetidos na sobreposição.
- **Quantos shorts: o usuário diz, a cada link.** Antes de começar qualquer vídeo/live, pergunte com
  `AskUserQuestion`: "Quantos reels você quer por bloco de 30 min?" (opções: até 3, até 5, só o melhor, ou outro
  número). A resposta vale para aquele link inteiro (todos os blocos) e vira o teto N do bloco. N é um **teto**,
  não uma meta: entregue só cortes **realmente bons** pelas regras de `references/viral-rules.md`; bloco fraco
  entrega menos que N, ou nenhum. Nunca complete número com corte fraco. Passou de N bons: fique com os N de
  maior `score` e renderize só esses. Achou os melhores, renderiza e encerra o bloco.
  Não guarde a resposta como padrão: no link seguinte, pergunte de novo (`ask_reels_each_link` no config).
- **Bloco por bloco, sem esperar o usuário** (`auto_next_block`): termine o bloco 1 (passos 1 a 7), mostre a
  lista do bloco e siga sozinho para o próximo, até o fim do vídeo. Enquanto um bloco transcreve ou renderiza,
  baixe o próximo. Bloco sem momento bom entrega menos cortes. Avise em uma linha a cada bloco pronto.
  Cada bloco termina com `progress.py done` (passo 6b), para nada ser repetido depois.
- **No máximo 2 jobs pesados ao mesmo tempo** (`max_parallel_jobs`: transcrição/render). Download pode rodar junto.
- **Renderizar sempre vem primeiro.** Assim que um bloco tiver o `clips.json`, renderize na hora, mesmo que passe
  do limite de 2 jobs por alguns minutos. Só depois siga com transcrição/small dos blocos seguintes. O usuário
  quer ver shorts prontos cedo, não só no fim do vídeo.
- **Layout do short: streamer em cima, o que ele transmite embaixo. Nunca o streamer nas duas metades.** Em
  cena de bate-papo (just chatting), em que a transmissão é só a webcam, não há conteúdo para a metade de baixo:
  **descarte o candidato** (não force `cam` nem `nocam`). Lobby, menu, tela de carregamento e seleção de
  personagem do jogo valem, pois são o que o streamer está transmitindo. Confira nos frames (passo 3b) que a
  parte de baixo mostra conteúdo diferente da webcam.
  **Webcam sobre o jogo que também apareceria embaixo** (ex.: canto inferior esquerdo): grave no `setup.json` do
  bloco `"split": "half"` (streamer e jogo do mesmo tamanho, 960/960, card na divisão) e `"game_focus_x"` (0 a 1,
  ex.: 1.0 = recorte do jogo na direita) para tirar a webcam da metade de baixo. Também vale por corte no `clips.json`.
- **Chat só da Twitch** (`download.chat_twitch`, via TwitchDownloaderCLI). YouTube não baixa chat; no lugar
  dele, o mapa de "mais repetidos" (`heatmap.json`) entra como sinal de apoio (`hype.weights.heatmap`).
- **Idioma:** detectado sozinho (`language_detect`), nunca fixo. Vídeo em outro idioma = **gringo**: legenda
  traduzida para português (passo 4c). Gancho, título e hashtags sempre em português.

## Identidade visual (não mexer sem o usuário pedir)

- **Logo oficial "RSK CORTES"** (`assets/logo.png`). No card entra redonda (`circle: true`) com margem preta
  (`pad` 0.18, tamanho 134), para a arte aparecer inteira.
- **Fontes** (em `fonts/`): Montserrat Black (gancho, etiqueta, título do `nocam`) e Poppins ExtraBold
  (legenda). Aprovadas pelo usuário.
- **`templates/cam.json` = "RSK CORTES, cores da logo"**: caixa escura em degradê, borda neon azul (#4B5BFF) →
  roxo (#C02BE8) → rosa (#FF3DCB) → laranja (#FF9A3C) com brilho, logo à esquerda, texto rosa neon (#FF4FD8),
  etiqueta do canal embaixo.
- **Card = UMA frase só.** O texto do card é uma frase única (o `hook`), quebrada automaticamente em até 2 linhas
  balanceadas, com **o mesmo tamanho e a mesma cor nas duas linhas**. Nunca duas frases diferentes, uma por linha
  (o `subhook` antigo, se existir, é emendado ao `hook` como continuação da mesma frase).
- **Tamanho do card (aprovado em 17/11/2026):** caixa de 168 px de altura (logo 134, `padding_y` 14,
  `line_gap` 4) e fonte do gancho 48 (mínimo 33). As duas linhas usam sempre o mesmo tamanho (o menor que
  coube); a largura da caixa acompanha o texto.
- **Etiqueta "RSK CORTES" na mesma cor do card:** fundo escuro em degradê (#14003A → #050008), borda neon em degradê
  (azul → roxo → rosa → laranja) e texto rosa neon (#FF4FD8), igual à caixa do card (`templates/cam.json`, `card.tag`).
- **Nome do canal** (`channel_name`): **RSK CORTES**.
- **Legenda do `cam`:** tamanho 69, palavra em destaque rosa (#FE5CCD), `gap` 30 px acima do card
  (`captions.anchor: "above_card"`). Nunca duas legendas ao mesmo tempo.
- **Saída:** H.264 / yuv420p / 30 fps / AAC; o script confere cada arquivo e falha se não bater.

## Passo -1 — Receber o link e ver se está ao vivo (o usuário só manda o link; sem perguntas)

Não comece a baixar. Primeiro olhe o vídeo sem baixar:
```
python scripts/download.py "<URL>" --probe
```
Mostra título, canal, duração, se está ao vivo e quantos pontos de heatmap tem (e, para link de canal da
Twitch, qual VOD vai ser usado). Mostra também o **histórico** desse vídeo (ver abaixo).

**Histórico (nunca repetir):** cada vídeo/live tem um arquivo em `<paths.work_root>/historico/<plataforma>_<id>.json`
com os trechos já cortados e os shorts já feitos (horário no original). O VOD de uma live no ar tem sempre o
mesmo id, então mandar o link de novo continua de onde parou. Detalhes: `python scripts/progress.py show work/<id>`.
- Vídeo novo: começa em 00:00:00.
- Já tem histórico: comece no "Continuar de" (fim do que já foi coberto menos a sobreposição) e não refaça o
  que já foi cortado. Se o vídeo inteiro já foi coberto e não está mais ao vivo, diga isso e pare.

**Live ainda no ar:**
- **Twitch, link de canal** (`twitch.tv/nome`): se o canal estiver ao vivo, o script acha o VOD da live atual
  (`twitch.tv/nome/videos`, o mais recente marcado como ao vivo) e usa o link dele. Sem VOD: avise e pare.
  Canal offline: peça o link de um VOD. **Nunca fique gravando até a live acabar.**
- **YouTube ao vivo:** baixa só o que já passou até agora (bloco fechado) e corta isso. `live_from_start` só é
  ligado para live no ar.
- Nos dois casos, ao terminar o que já passou, diga em uma linha: "A live continua. Me mande o link de novo
  depois que eu continuo de HH:MM:SS, sem repetir" (o histórico guarda onde parou).

**Uma única pergunta por link: quantos reels por bloco** (ver "Quantos shorts"). Faça essa pergunta logo depois do
`--probe` e antes de baixar, e espere a resposta. Fora essa, **não faça perguntas.** Não pergunte qual trecho nem o
tamanho do bloco: é sempre o vídeo inteiro (live no ar: tudo o que já passou), num bloco só até 1 h e em blocos
de 30 min acima disso (ver "Sempre o vídeo inteiro").
Também não pergunte sobre permissão de repostagem (o usuário já disse que tem), nome do canal, card, webcam,
idioma, modelo, cores. Antes de tudo, diga em uma ou duas linhas: o resumo do vídeo (título, canal, duração),
se é um bloco só (até 1 h) ou quantos blocos de 30 min (acima de 1 h) e quanto deve demorar. Depois comece.

## Passo 0 — Conferir instalação (primeira vez ou PC novo)

`python scripts/check_setup.py` confere ffmpeg, pacotes Python (yt-dlp, yt-dlp-ejs, bgutil-ytdlp-pot-provider,
faster-whisper, av>=14,<17, numpy, pillow), Node.js, o gerador do PO token e o TwitchDownloaderCLI, e diz o
comando exato para instalar o que faltar. Cookies e problemas do YouTube: `paths.setup_guide`.

## Passo 1 — Baixar

```
python scripts/download.py "<URL>" --out work/<id>-b<N> --section <início>-<fim do bloco N>
```
Um `work/<id>-b<N>/` por bloco (vídeo de um bloco só: `work/<id>/`, sem `--section`).
Gera `source.mp4` (até 1080p), `info.json`, e quando houver: `section.json`, `heatmap.json` (YouTube),
`chat.json` (Twitch).
- Com `--section` o corte é por cópia de stream e o arquivo começa no keyframe anterior. O script **mede o início
  real** (ffprobe) e grava em `section.json` o offset REAL. Chat da Twitch, heatmap e "horário no original" usam
  esse offset. Os tempos de `transcript.json`, `cands.json` e `clips.json` são sempre **do arquivo**.
- Cookies só quando o vídeo pede login/idade, e sempre por cópia temporária do arquivo master.

## Passo 2 — Detectar o idioma e transcrever o bloco inteiro com o tiny

```
python scripts/transcribe.py work/<id>/source.mp4
```
Na primeira vez detecta o idioma: 3 a 5 trechos de ~30 s espalhados pelo meio do vídeo (sem começo e fim),
modelo `tiny`, vence o idioma que mais aparece → `work/<id>/lang.json`. As transcrições seguintes usam esse
idioma (`--language xx` só se a detecção errar). Depois transcreve tudo com `transcribe_fast` (tiny, beam 1):
precisão baixa, serve para ler e achar candidatos. Se o texto vier ilegível, suba para `base` no config.

## Passo 3 — Ler tudo em blocos de 10 minutos e listar candidatos

```
python scripts/read_blocks.py work/<id>              # lista os blocos
python scripts/read_blocks.py work/<id> --block N    # lê o bloco N (10 min)
```
**Leia todos os blocos, do primeiro ao último.** Procure piadas, reviravoltas, discussões, situações
inesperadas, histórias com desfecho e reações fortes (`references/viral-rules.md`). Anote cada candidato em
`cands.json`: `[{"id":1,"start":"00:08:05","end":"00:08:40","why":"..."}]`. Seja generoso: anote tudo que pode ser bom; a seleção final vem depois.

**Apoio, não filtro:** `python scripts/find_hype.py work/<id> --top 15` (áudio, chat da Twitch e "clipa",
heatmap do YouTube, movimento). Use para conferir seus candidatos e achar trechos que a leitura deixou passar.
Pico sem graça é descartado; candidato bom sem pico fica. Palavras de um momento (tempo do arquivo):
`find_hype.py work/<id> --words 00:08:05-00:08:35` (em vídeo do YouTube mostra só a fala).

## Passo 3b — Olhar os frames dos candidatos

```
python scripts/extract_frames.py work/<id> --candidates work/<id>/cands.json --frames 6
```
Abra e analise `work/<id>/frames/cand<N>.jpg` (Read): pega momentos visuais sem fala (batida, explosão, fuga,
susto) e confirma ou derruba candidatos.

## Passo 3c — Retranscrever só os candidatos com o small

```
python scripts/transcribe.py work/<id>/source.mp4 --candidates work/<id>/cands.json
```
Usa `transcribe_refine` (small, beam 5) e troca só esses trechos no `transcript.json`. A margem é
`transcribe_refine.pad_seconds` (10 s), nunca menor que `pad_folga`: assim o `check_cut.py` tem as palavras
precisas em volta do início e do fim, e um corte "com folga" tem legenda nos extras.

## Passo 4 — Escolher os cortes e escrever `clips.json`

Releia os candidatos com o small e os frames na cabeça. Escolha pela história/graça, não pelo volume.
Antes de renderizar, rode `python scripts/progress.py check work/<id>`: ele aponta cortes que repetem um short
já feito (de outro bloco ou de uma vez anterior). Descarte os repetidos.
Descarte o que não faz sentido sem contexto. Cada corte começa no gancho e termina logo após o desfecho.

**Início e fim perfeitos** (o short é postado sem editar; regras completas em `references/viral-rules.md`):
- **Início:** no gancho, a primeira frase ou ação que já prende (nunca cumprimento, "então", "tipo", silêncio,
  menu, loading). Contexto só se precisar, com a frase mínima (até ~3 s) antes do gancho. Em fronteira de
  palavra: início = começo da primeira palavra − 0,15 s, nunca no meio de palavra ou sílaba. Momento visual
  (batida, fuga, susto): 0,5 a 1 s antes da ação, conferido nos frames. Nunca num corte de câmera ou transição.
- **Fim:** 0,3 a 0,8 s depois da última palavra do desfecho ou da reação. Risada ou grito: corte quando o som
  começa a cair, nunca no pico. Nada depois do desfecho ("bom", "enfim", "chat", troca de assunto). Se houver
  troca de cena logo depois, o fim fica antes dela. Quando der, um final que emende com o começo (loop).
- Depois de escrever o `clips.json`, **sempre** confira cada corte com `check_cut.py` (passo 4d) antes de renderizar.

```json
[
  {
    "id": 1,
    "style": "cam",
    "start": "00:08:05.0",
    "end": "00:08:33.5",
    "hook": "EU TAVA NO FLOW STATE E PEGUEI TODAS AS BOLAS",
    "title": "Ele entrou no flow state e pegou todas as bolas 😂 #alanzoka",
    "description": "Uma frase curta para a descrição.",
    "hashtags": ["#gta6", "#shorts", "#cortes", "#alanzoka", "#gameplay"],
    "type": "Jogada",
    "reason": "piada + reviravolta; chat em KKKK",
    "score": 9
  }
]
```
- `aviso` (opcional): alerta que sai no kit de postagem, ex.: "música do jogo alta: risco de som mudo".
- `title`, `description` e `hashtags` são **obrigatórios** em todo corte (vão para o kit; título e hashtags também para o Notion).
- `style`: `"cam"` (com webcam) ou `"nocam"`. `hook` = a frase do card, UMA frase só (até ~8 palavras, sem emoji,
  em português); o script quebra em 2 linhas sozinho. Não use `subhook`. `title`, `description`, `hashtags` vão para o kit de postagem.
- `type`: Reação, Fail, Jogada, Piada, História ou Discussão (fica no `renders.json`; o Notion não usa mais).
- `start`/`end` = o corte exato do arquivo (com 2 casas decimais, ex.: `00:08:14.73`), conferido no passo 4d.
- Opcionais: `"folga": true` (só se o usuário pedir), `"captions": false`, `"cam": [x,y,w,h]`, `"captions_pt"` (passo 4c), `"notion_page_id"` (passo 8).

## Passo 4d — Conferir início e fim de cada corte (antes de renderizar, sempre)

Depois de escrever o `clips.json`, para **cada** corte:
```
python scripts/check_cut.py work/<id> --clip N
```
Mostra, no início e no fim: as palavras com tempo de 3 s antes a 3 s depois (passada small do `transcript.json`),
o volume do áudio a cada 0,1 s, as trocas de cena perto do corte e uma folha de frames
(`frames/cut<N>_inicio.jpg` e `frames/cut<N>_fim.jpg`, em ordem: −1,0 −0,5 0 +0,5 +1,0 +1,5 s no início e
−1,5 −1,0 −0,5 0 +0,5 +1,0 s no fim). Também dá alertas com o tempo certo (corte no meio de palavra, folga fora
da regra, fim no pico do som, transição no começo ou no fim).
1. Leia as palavras e o volume, **abra as duas folhas de frames** (Read) e ajuste `start`/`end` no `clips.json`
   pelas regras de "Início e fim perfeitos".
2. Rode `check_cut.py` de novo até não sobrar alerta (ou até o alerta restante ter um motivo, ex.: momento
   visual sem fala no começo).
3. Só então exporte a legenda (passo 4c, se gringo) e renderize (passo 5). Se o `start`/`end` mudar depois de
   traduzir, exporte e confira o `captions_pt` de novo.

## Passo 4b — Ver o vídeo e escolher o estilo

`python scripts/make_shorts.py work/<id> --snapshot` → `snapshot.jpg` (6 quadros). Olhe e decida:
1. **Tem webcam?** Sim → `cam`; estime o retângulo em frações `x,y,w,h` e confira com
   `make_shorts.py work/<id> --cam x,y,w,h --snapshot` (caixa vermelha dentro da webcam, sem barras de
   overlay). Fica salvo em `setup.json`. Não → `nocam`.
2. **Legenda gravada na imagem?** Sim → `--burned-subs` (sem legenda palavra por palavra).

## Passo 4c — Vídeo gringo: legenda em português

Se `lang.json` não for `pt`, a legenda de cada corte sai traduzida (o render recusa o corte sem tradução):
1. `python scripts/make_shorts.py work/<id> --export-captions N` → `captions_N.json` com as frases originais
   do short inteiro, cada uma com seu tempo `s`/`e` (tempo do arquivo).
2. Traduza **frase por frase** para português do Brasil, mantendo `s`/`e` de cada frase.
3. Revise cada frase pensando na cena: gíria, ironia e palavrão soando natural em português, não literal.
4. Grave a lista revisada em `clips.json` como `"captions_pt": [{"s": 80.0, "e": 82.4, "text": "..."}]`.

O `make_shorts.py` usa só o `captions_pt`: cada frase vira legendas no tempo da frase original (quebrando pelo
`max_words`/`max_chars` do template) e o destaque palavra por palavra é distribuído proporcionalmente ao tamanho
das palavras dentro do tempo da frase.

## Passo 5 — Renderizar (direto, sem esperar aprovação do gancho)

`python scripts/make_shorts.py work/<id> [--only 1,2]`

- **`cam`:** topo 768 px = webcam; baixo 1152 px = gameplay; card centrado na divisão (y=768) o vídeo todo;
  legenda acima do card.
- **`nocam`** (layout `stack` em `nocam.json`): fundo desfocado, logo RSK redonda com anel rosa→laranja no topo,
  gancho em degradê GTA com contorno e brilho, gameplay no meio, legenda rosa embaixo.
- Cada short = exatamente o corte (`start` a `end`); com `"folga": true`, o corte + `pad_folga` dos dois lados.
  O script imprime, por short: arquivo, gancho e "corte sugerido no arquivo" (sem folga, o arquivo inteiro:
  0:00 até a duração), e grava `shorts/renders.json` e `shorts/posting-kit.md`.

## Passo 6 — Conferir e mostrar a lista do bloco

1. `make_shorts.py work/<id> --preview` → `shorts/preview.jpg` (3 quadros por short). Abra e confira legenda,
   recorte da webcam e card sem cobrir rosto.
2. No fim de cada bloco, mostre a lista: **arquivo, gancho (texto único), corte sugerido no arquivo**, e a pasta.
   O `posting-kit.md` tem, por short: título (<70 caracteres), descrição, 5–8 hashtags, corte sugerido no
   arquivo (sem folga é o arquivo inteiro, ex.: "0:00 a 0:28"), horário no original e a ordem sugerida para postar.
3. No Windows, abra imagens com `Start-Process <png>`; `.mp4` peça para abrir pelo Explorer.

## Passo 6a — Organizar os shorts na pasta numerada (fim de CADA bloco)

```
python scripts/organize_shorts.py work/<id>-b<N>
```
Os shorts finais ficam em **`paths.shorts_root`** (padrão `C:\cortes\shorts`), **uma subpasta numerada por link**:
o primeiro link que o usuário mandou é a pasta `1`, o segundo é a `2`, e assim por diante. **Todos os blocos do
mesmo link vão para a mesma pasta** (mandar o mesmo link de novo continua nela). Cada arquivo sai como
`NN_GANCHO DO SHORT.mp4` (NN continua de bloco em bloco) e a pasta ganha um `lista-de-postagem.md` (título,
descrição, hashtags e horário no original). O registro de qual link é qual número fica em
`shorts\_registro.json` (não mexer). A pasta fica **fora** de `work/`, então a limpeza do dia nunca apaga.
Avise o usuário em qual pasta numerada os shorts ficaram. No Notion, o campo `Arquivo` usa `final_file` do
`renders.json` (caminho dentro de `shorts\<número>\`).

## Passo 6b — Gravar no histórico (fim de CADA bloco, sempre)

```
python scripts/progress.py done work/<id> --block-minutes <30|60>
```
Grava o trecho do bloco (tempo do original, com o offset real) e os shorts renderizados no histórico do vídeo.
Rode mesmo quando o bloco não teve nenhum short: assim o trecho conta como já visto. Depois atualize a linha
do vídeo em "Progresso dos Vídeos" no Notion (passo 8, item 3).

## Passo 7 — Trocar gancho (quando o usuário pedir)

O usuário manda `corte N: GANCHO` (uma frase só). Edite `hook` do corte N no `clips.json`, rode
`make_shorts.py work/<id> --only N` (só ele é renderizado de novo) e atualize a **mesma** linha do Notion
(passo 8, pelo `notion_page_id`) e rode `progress.py done work/<id>` de novo (atualiza, não duplica).
O modo bloco por bloco continua sozinho.

## Passo 7b — Ajustar início/fim ou pedir folga (quando o usuário pedir)

- `corte N: começa X s antes` / `corte N: começa X s depois`: `start` do corte N − X / + X.
- `corte N: termina X s antes` / `corte N: termina X s depois`: `end` do corte N − X / + X.
- `esse com folga` / `corte N com folga`: `"folga": true` no corte N (o arquivo ganha `pad_folga` s antes e depois).

Em todos: edite só o corte N no `clips.json`, rode `check_cut.py work/<id> --clip N` para ver se o novo ponto não
caiu no meio de palavra ou numa transição (avise em uma linha se cair, mas faça o que o usuário pediu), exporte e
ajuste o `captions_pt` se for gringo, rode `make_shorts.py work/<id> --only N`, `organize_shorts.py` e
`progress.py done work/<id>`, e atualize a **mesma** linha do Notion se o `Arquivo` mudar (pelo
`notion_page_id`, nunca crie outra).

## Passo 8 — Registrar no Notion (automático)

Usa o MCP do Notion do usuário (`claude mcp add --transport http --scope user notion https://mcp.notion.com/mcp`,
depois `/mcp` para autorizar). Bases em `config.json` → `notion`:
`resultados_data_source` ("Resultados dos Cortes") e `canais_data_source` ("Canais para Cortes").
Os dados de cada short estão em `shorts/renders.json`. Base de progresso: `progresso_data_source`
("Progresso dos Vídeos").

Para cada short renderizado:
1. **Linha em "Resultados dos Cortes"** (só o que o usuário precisa para postar: Gancho, Título, Hashtags e Arquivo, mais o Link para separar;
   aprovado em 17/11/2026):
   - `Gancho` (título): **um texto só**, sem barra: `hook_text` do `renders.json` (ex.: "EXPLODIU TUDO NA CARA
     DA POLÍCIA")
   - `Título`, `Hashtags`: os mesmos do kit de postagem (`title`, `hashtags` separadas por espaço). Sempre
     preencha os dois. A descrição fica só no kit (não vai para o Notion).
   - `Arquivo`: caminho final do .mp4 na pasta numerada (`final_file` do `renders.json`, depois do passo 6a)
   - `Link` (seleção): `"N · <título do vídeo>"`, com N = número da pasta desse link
     (`shorts\_registro.json` → `links`, o mesmo de `C:\cortes\shorts\N`) e o título do `info.json`, ex.:
     `"1 · iShowSpeed Plays I Wanna Test This Game.."`. Todos os blocos do mesmo link usam a mesma opção. Link
     novo: crie a opção (`ALTER COLUMN "Link"` listando as opções antigas + a nova, cor diferente da anterior).
     A visão "Por link" agrupa a tabela por esse campo, um bloco por link.
   Só esses 5 campos: não crie outros nesta base. Grave o id da página criada no corte (`"notion_page_id"` no
   `clips.json`). Se o corte já tiver `notion_page_id` (gancho trocado, tempo ajustado), **atualize essa linha**
   (`Gancho`, `Arquivo` e o que mais mudou), não crie outra.
2. **Base de canais** ("Canais para Cortes", opcional): se existir e não estiver na lixeira, procure o canal
   (título `Canal`); se não existir, crie com `Canal`, `Link` (`channel_url`/`uploader_url` do `info.json`),
   `Plataforma` (YouTube, Twitch, Kick ou Outro) e `Status` "Cortando". Para cada short novo: `Cortes feitos` +1
   e `Último corte` = hoje. Se a base estiver na lixeira ou der erro, pule este item sem avisar a cada short
   (uma linha no fim do bloco basta).
3. **Progresso do vídeo** (uma linha por vídeo/live, no fim de cada bloco, depois do `progress.py done`;
   formato aprovado em 17/11/2026): `python scripts/progress.py notion work/<id>` imprime os campos prontos:
   - `Streamer` (título da linha): nome do canal/streamer (`channel`/`uploader` do `info.json`)
   - `Link da live`: link do vídeo/live
   - `ID do vídeo` e `Trechos cortados` (ex.: `00:00:00–01:12:47`): ficam escondidos na visão "Lives"; são a
     reserva da skill caso o histórico do PC (`historico/`) suma. Sempre preencha os dois.
   Só esses 4 campos (não crie outros nesta base). Status e aviso ("A live continua…", "Concluído") vão só para a
   mensagem no chat, não para o Notion. Se `notion_page_id` vier vazio, crie a linha e guarde o id com
   `progress.py set-notion work/<id> <page_id>`; se vier preenchido, **atualize essa linha** (nunca crie outra).
   Se o histórico local sumir, procure a linha pelo `ID do vídeo` antes de criar e use os `Trechos cortados`
   dela para não repetir.

Se o Notion não estiver disponível, renderize normal e avise em uma linha ("Notion indisponível: os shorts não
foram registrados"); não trave.

**Análise (só quando o usuário pedir):** a base de resultados não guarda mais views nem retenção. Se o usuário
pedir análise de desempenho, diga isso e pergunte se ele quer voltar a anotar views (precisa de 20 ou mais
shorts com views, `notion.min_rows_for_patterns`).

## Limpeza do dia (automática, ao ligar o note)

Instalada uma vez com `python scripts/install_cleanup.py` (atalho escondido na pasta Inicializar do Windows,
sem admin; `--remove` desinstala). Toda vez que o usuário entra no Windows, `scripts/cleanup.py` apaga em
`paths.work_root` tudo o que não foi mexido nas últimas `cleanup.idle_hours` (3) horas: vídeos baixados,
transcrições, frames, temporários **e os shorts prontos**. Fica só `historico/` (de onde cada vídeo/live parou).
O Notion não é mexido. Por isso:
- No fim de cada bloco, avise: "os shorts ficam na pasta até você desligar; amanhã, ao ligar, são apagados".
- No dia seguinte, o mesmo link continua de onde parou (pelo histórico), sem repetir.
- Trocar gancho de um short do dia anterior não dá mais (os arquivos foram apagados): é preciso cortar de novo.
- Teste sem apagar: `python scripts/cleanup.py --dry-run`. Registro das limpezas: `historico/limpeza.log`.

## Gameplay solo (lançamento do GTA 6, 19/11/2026) e calibração

- **Gameplay solo não tem chat nem webcam:** a leitura da transcrição (se o usuário narra) e os frames viram a
  fonte principal de candidatos (passos 2 a 3b). Use `nocam`.
- **Música do rádio do jogo** dá claim/mute: pular trechos com música licenciada alta (ver `viral-rules.md`).
- **Abertura do jogo: sempre candidata em toda live** (primeira tela, logo, primeira cena), mesmo com menu ou
  loading na imagem e mesmo sem pico nos sinais (o `find_hype.py` ignora tela parada: procure a abertura na
  leitura e nos frames). O corte começa na reação, não na espera do carregamento. Música do jogo alta: corte
  mesmo assim e ponha `"aviso": "música do jogo alta: risco de som mudo"` no corte (sai no kit).
  **No máximo um short de abertura por live** (vale também entre dias: confira com `progress.py check`).
- **Capacidade:** o limite é escolher e conferir, não renderizar. Não force número: a quantidade
  de cortes depende só de quantos momentos bons o bloco tem.
- **Teste cego de calibração (a pedido do usuário):** ele anota os cortes que faria numa live inteira sem me
  mostrar; eu rodo o fluxo e comparamos (coincidências, só dele, só meus, e por quê). Os padrões que ele explicar
  vão para `references/viral-rules.md` e para a memória.
- **Postagem:** espalhar os shorts ao longo dos dias; os melhores primeiro.

## Como o usuário edita depois

- **Gancho:** "corte N: GANCHO" (passo 7). **Tempo do corte:** "corte N: começa/termina X s antes/depois" ou
  "esse com folga" (passo 7b). Se mudar título ou hashtags, atualize também a linha do Notion.
- **Visual** (cores, tamanhos, posição, logo, nome do canal): `templates/cam.json` ou `nocam.json`.
- Antes de sobrescrever shorts já aprovados, guarde cópia (ex.: `shorts_antigo/`).

## Notas

- O usuário disse ter permissão para repostar os cortes que pede; não pergunte de novo.
- Tudo roda localmente, exceto o download e o registro no Notion.
- Preferências do usuário e identidade do canal também estão na memória do Claude (pasta do projeto).
