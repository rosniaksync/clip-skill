---
name: gta-clipper-skill
description: Transforma qualquer live ou vídeo longo (YouTube, Twitch VOD, Kick etc.) em shorts verticais prontos para postar (1080x1920, card de gancho, legenda palavra por palavra, 10 s extras antes e depois). Use quando o usuário colar um link de live/vídeo e pedir shorts, cortes, reels, clips, ou "is stream se viral shorts banao".
---

# Live → Shorts virais

O usuário cola o link de uma live. Você baixa, detecta o idioma, transcreve (tiny no vídeo todo), lê tudo em
blocos de 10 min, olha os frames, retranscreve os candidatos com o small, escolhe os cortes, renderiza cada um
como short 1080x1920 (card de gancho, legenda palavra por palavra, ±10 s) e registra cada short no Notion.

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
- **Extras no arquivo:** `pad_before` / `pad_after` (10 s). O short é renderizado inteiro (card, legenda, layout)
  de `start - pad_before` até `end + pad_after`, respeitando o começo e o fim do vídeo. O `start`/`end` do
  `clips.json` é o **corte sugerido**; o kit e o Notion mostram onde ele fica dentro do arquivo (ex.: 0:10 a 0:47).
- **Recuo antes do pico:** `pre_roll_seconds` (15 s): a reação vem depois do fato. Depois apare para a primeira
  frase/ação forte (gancho primeiro).
- **Blocos de 1 hora** (`chunk_minutes`) com 5 min de sobreposição (`chunk_overlap_minutes`) via
  `download.py --section`; descarte cortes repetidos na sobreposição. 1 a 3 cortes por bloco, sem forçar.
- **Bloco por bloco, sem esperar o usuário** (`auto_next_block`): termine o bloco 1 (passos 1 a 7), mostre a
  lista do bloco e siga sozinho para o próximo, até o fim do vídeo. Enquanto um bloco transcreve ou renderiza,
  baixe o próximo. Bloco sem momento bom entrega menos cortes. Avise em uma linha a cada bloco pronto.
- **No máximo 2 jobs pesados ao mesmo tempo** (`max_parallel_jobs`: transcrição/render). Download pode rodar junto.
- **Chat só da Twitch** (`download.chat_twitch`, via TwitchDownloaderCLI). YouTube não baixa chat; no lugar
  dele, o mapa de "mais repetidos" (`heatmap.json`) entra como sinal de apoio (`hype.weights.heatmap`).
- **Idioma:** detectado sozinho (`language_detect`), nunca fixo. Vídeo em outro idioma = **gringo**: legenda
  traduzida para português (passo 4c). Gancho, subgancho, título e hashtags sempre em português.

## Identidade visual (não mexer sem o usuário pedir)

- **Logo oficial "RSK CORTES"** (`assets/logo.png`). No card entra redonda (`circle: true`) com margem preta
  (`pad` 0.18, tamanho 190), para a arte aparecer inteira. Logo antiga "Cortes GTA 6": `assets/logo_gta6_loucuras.png`.
- **Fontes** (em `fonts/`): Montserrat Black (gancho, subgancho, etiqueta, título do `nocam`) e Poppins ExtraBold
  (legenda). Aprovadas pelo usuário.
- **`templates/cam.json` = "RSK CORTES, cores da logo"**: caixa escura em degradê, borda neon azul (#4B5BFF) →
  roxo (#C02BE8) → rosa (#FF3DCB) → laranja (#FF9A3C) com brilho, logo à esquerda, gancho rosa neon (#FF4FD8),
  subgancho azul-gelo (#CFE3FF), etiqueta do canal embaixo. Backups: `cam_gta6_loucuras.json`, `cam_laranja.json`.
- **Nome do canal** (`channel_name`): **RSK CORTES**.
- **Legenda do `cam`:** tamanho 69, palavra em destaque rosa (#FE5CCD), `gap` 30 px acima do card
  (`captions.anchor: "above_card"`). Nunca duas legendas ao mesmo tempo.
- **Saída:** H.264 / yuv420p / 30 fps / AAC; o script confere cada arquivo e falha se não bater.

## Passo -1 — Receber o link, ver se está ao vivo e perguntar (o usuário só manda o link)

Não comece a baixar. Primeiro olhe o vídeo sem baixar:
```
python scripts/download.py "<URL>" --probe
```
Mostra título, canal, duração, se está ao vivo e quantos pontos de heatmap tem (e, para link de canal da
Twitch, qual VOD vai ser usado).

**Live ainda no ar:**
- **Twitch, link de canal** (`twitch.tv/nome`): se o canal estiver ao vivo, o script acha o VOD da live atual
  (`twitch.tv/nome/videos`, o mais recente marcado como ao vivo) e usa o link dele. Sem VOD: avise e pare.
  Canal offline: peça o link de um VOD. **Nunca fique gravando até a live acabar.**
- **YouTube ao vivo:** baixa só o que já passou até agora (bloco fechado) e corta isso. Avise em uma linha que
  a live ainda está rolando e que dá para rodar de novo depois para o resto. `live_from_start` só é ligado para
  live no ar.

Depois use a ferramenta de perguntas (AskUserQuestion), **uma rodada, no máximo 2 perguntas**, só sobre o que
você não descobre sozinho, com um resumo do vídeo (título, canal, duração), primeira opção = recomendada:
1. **Quantos shorts?** Padrão: 2 por hora de vídeo.
2. **Qual trecho?** Só para vídeos de 2 h ou mais (primeira hora / intervalo digitado / vídeo inteiro em blocos de 1 h).

Não pergunte sobre permissão de repostagem (o usuário já disse que tem), nome do canal, card, webcam, idioma,
modelo, cores. Depois das respostas, diga em uma linha o que vai fazer e quanto deve demorar, e comece.
Sem resposta, use os padrões e diga quais usou.

## Passo 0 — Conferir instalação (primeira vez ou PC novo)

`python scripts/check_setup.py` confere ffmpeg, pacotes Python (yt-dlp, yt-dlp-ejs, bgutil-ytdlp-pot-provider,
faster-whisper, av>=14,<17, numpy, pillow), Node.js, o gerador do PO token e o TwitchDownloaderCLI, e diz o
comando exato para instalar o que faltar. Cookies e problemas do YouTube: `paths.setup_guide`.

## Passo 1 — Baixar

```
python scripts/download.py "<URL>" --out work/<id> [--section 00:00:00-01:00:00]
```
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
`cands.json`: `[{"id":1,"start":"00:08:05","end":"00:08:40","why":"..."}]`. Seja generoso (~4x o pedido).

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
`transcribe_refine.pad_seconds`, nunca menor que `pad_before`/`pad_after`, para a legenda cobrir os extras.

## Passo 4 — Escolher os cortes e escrever `clips.json`

Releia os candidatos com o small e os frames na cabeça. Escolha pela história/graça, não pelo volume.
Descarte o que não faz sentido sem contexto. Cada corte começa no gancho e termina logo após o desfecho.

```json
[
  {
    "id": 1,
    "style": "cam",
    "start": "00:08:05.0",
    "end": "00:08:33.5",
    "hook": "EU TAVA NO FLOW STATE",
    "subhook": "PEGUEI TODAS AS BOLAS",
    "title": "Ele entrou no flow state e pegou todas as bolas 😂 #alanzoka",
    "description": "Uma frase curta para a descrição.",
    "hashtags": ["#gta6", "#shorts", "#cortes", "#alanzoka", "#gameplay"],
    "type": "Jogada",
    "reason": "piada + reviravolta; chat em KKKK",
    "score": 9
  }
]
```
- `style`: `"cam"` (com webcam) ou `"nocam"`. `hook` = linha 1 do card, `subhook` = linha 2 (máx. ~5 palavras,
  sem emoji, em português). `title`, `description`, `hashtags` vão para o kit de postagem.
- `type` (para o Notion): Reação, Fail, Jogada, Piada, História ou Discussão.
- `start`/`end` em fronteiras de palavra = corte sugerido (o arquivo ganha ±10 s sozinho).
- Opcionais: `"captions": false`, `"cam": [x,y,w,h]`, `"captions_pt"` (passo 4c), `"notion_page_id"` (passo 8).

## Passo 4b — Ver o vídeo e escolher o estilo

`python scripts/make_shorts.py work/<id> --snapshot` → `snapshot.jpg` (6 quadros). Olhe e decida:
1. **Tem webcam?** Sim → `cam`; estime o retângulo em frações `x,y,w,h` e confira com
   `make_shorts.py work/<id> --cam x,y,w,h --snapshot` (caixa vermelha dentro da webcam, sem barras de
   overlay). Fica salvo em `setup.json`. Não → `nocam`.
2. **Legenda gravada na imagem?** Sim → `--burned-subs` (sem legenda palavra por palavra).

## Passo 4c — Vídeo gringo: legenda em português

Se `lang.json` não for `pt`, a legenda de cada corte sai traduzida (o render recusa o corte sem tradução):
1. `python scripts/make_shorts.py work/<id> --export-captions N` → `captions_N.json` com as frases originais
   do short inteiro (com os ±10 s), cada uma com seu tempo `s`/`e` (tempo do arquivo).
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
- Cada short = corte + `pad_before`/`pad_after`. O script imprime, por short: arquivo, gancho/subgancho e
  "corte sugerido no arquivo", e grava `shorts/renders.json` e `shorts/posting-kit.md`.

## Passo 6 — Conferir e mostrar a lista do bloco

1. `make_shorts.py work/<id> --preview` → `shorts/preview.jpg` (3 quadros por short). Abra e confira legenda,
   recorte da webcam e card sem cobrir rosto.
2. No fim de cada bloco, mostre a lista: **arquivo, gancho / subgancho, corte sugerido no arquivo**, e a pasta.
   O `posting-kit.md` tem, por short: título (<70 caracteres), descrição, 5–8 hashtags, corte sugerido no
   arquivo (ex.: "0:10 a 0:47"), horário no original e a ordem sugerida para postar.
3. No Windows, abra imagens com `Start-Process <png>`; `.mp4` peça para abrir pelo Explorer.

## Passo 7 — Trocar gancho (quando o usuário pedir)

O usuário manda `corte N: GANCHO / SUBGANCHO`. Edite `hook`/`subhook` do corte N no `clips.json`, rode
`make_shorts.py work/<id> --only N` (só ele é renderizado de novo) e atualize a **mesma** linha do Notion
(passo 8, pelo `notion_page_id`). O modo bloco por bloco continua sozinho.

## Passo 8 — Registrar no Notion (automático)

Usa o MCP do Notion do usuário (`claude mcp add --transport http --scope user notion https://mcp.notion.com/mcp`,
depois `/mcp` para autorizar). Bases em `config.json` → `notion`:
`resultados_data_source` ("Resultados dos Cortes") e `canais_data_source` ("Canais para Cortes").
Os dados de cada short estão em `shorts/renders.json`.

Para cada short renderizado:
1. **Canal:** procure o canal na base de canais (título `Canal`). Se não existir, crie com `Canal`, `Link`
   (link do canal, `channel_url`/`uploader_url` do `info.json`), `Plataforma` (YouTube, Twitch, Kick ou Outro)
   e `Status` "Cortando".
2. **Linha em "Resultados dos Cortes":**
   - `Gancho` (título): "GANCHO / SUBGANCHO"
   - `Canal`: relação com a página do canal
   - `Data do corte`: hoje
   - `Link do vídeo`: `video_url`
   - `Horário no original`: `original_time` (tempo absoluto do vídeo, ex.: 01:12:05 a 01:12:41)
   - `Corte sugerido no arquivo`: `suggested_cut_in_file` (ex.: 0:10 a 0:47)
   - `Arquivo`: caminho do .mp4 (`file`)
   - `Estilo`: cam / nocam
   - `Tipo de momento`: `type` do corte (Reação, Fail, Jogada, Piada, História, Discussão)
   - `Idioma de origem`: PT ou Gringo (`origin_language`)
   - `Status`: "Renderizado"
   Grave o id da página criada no corte (`"notion_page_id"` no `clips.json`). Se o corte já tiver
   `notion_page_id` (gancho trocado e renderizado de novo), **atualize essa linha**, não crie outra.
3. **Base de canais:** `Cortes feitos` +1 e `Último corte` = hoje (só para linha nova, não para atualização).
4. Não preencha Views 24h, Views 7d, Retenção %, Postado em, Data da postagem nem Observação (são do usuário).

Se o Notion não estiver disponível, renderize normal e avise em uma linha ("Notion indisponível: os shorts não
foram registrados"); não trave.

**Análise (só quando o usuário pedir):** leia a base de resultados, mas só aponte padrões se houver **20 ou mais
linhas com views preenchidas** (`notion.min_rows_for_patterns`). Com menos, diga quantas faltam.

## Gameplay solo (lançamento do GTA 6, 19/11/2026) e calibração

- **Gameplay solo não tem chat nem webcam:** a leitura da transcrição (se o usuário narra) e os frames viram a
  fonte principal de candidatos (passos 2 a 3b). Use `nocam`.
- **Música do rádio do jogo** dá claim/mute: pular trechos com música licenciada alta (ver `viral-rules.md`).
- **Capacidade (estimativa, medir no Aspire 16 quando chegar):** ~10-15 shorts por hora de trabalho no Aspire e
  ~6-10 no PC antigo (i5-2400); o limite é escolher e conferir, não renderizar. Contar ~4 bons cortes por hora de
  gameplay gravado. Não force número.
- **Teste cego de calibração (a pedido do usuário):** ele anota os cortes que faria numa live inteira sem me
  mostrar; eu rodo o fluxo e comparamos (coincidências, só dele, só meus, e por quê). Os padrões que ele explicar
  vão para `references/viral-rules.md` e para a memória.
- **Postagem:** espalhar os shorts ao longo dos dias; os melhores primeiro.
- **Ideia pendente:** ler marcadores de capítulo do OBS (ou "clipa" falado) como candidatos de maior peso.

## Como o usuário edita depois

- **Gancho:** "corte N: GANCHO / SUBGANCHO" (passo 7). **Tempo do corte:** editar `start`/`end` em
  `clips.json` e rodar `make_shorts.py work/<id> --only N`.
- **Visual** (cores, tamanhos, posição, logo, nome do canal): `templates/cam.json` ou `nocam.json`.
- Antes de sobrescrever shorts já aprovados, guarde cópia (ex.: `shorts_antigo/`).

## Notas

- O usuário disse ter permissão para repostar os cortes que pede; não pergunte de novo.
- Tudo roda localmente, exceto o download e o registro no Notion.
- Preferências do usuário e identidade do canal também estão na memória do Claude (pasta do projeto).
