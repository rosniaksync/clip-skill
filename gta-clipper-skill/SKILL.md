---
name: gta-clipper-skill
description: Transforma qualquer live ou vídeo longo (YouTube, Twitch VOD, Kick etc.) em shorts verticais prontos para postar (1080x1920, card de gancho, legenda palavra por palavra). Use quando o usuário colar um link de live/vídeo e pedir shorts, cortes, reels, clips, ou "is stream se viral shorts banao".
---

# Live → Shorts virais

O usuário cola o link de uma live. Você baixa, transcreve (tiny no vídeo todo, small nos candidatos), lê tudo, olha os frames,
e renderiza cada corte como um short 1080x1920 com card de gancho e legenda palavra por palavra.
Trabalhe em `work/<id>/` (na pasta do usuário, por exemplo C:\cortes\work\<id>) e entregue em `shorts/`.

Scripts em `scripts/` desta skill: `python <skill-dir>/scripts/<nome>.py`.
Responda no idioma do usuário (português do Brasil) e mantenha as atualizações curtas.
No Windows, rode Python com `PYTHONIOENCODING=utf-8` (senão o console quebra em acentos e símbolos).
Não use `python -I` (ele esconde o Pillow instalado no perfil do usuário).

## Configuração (tudo em `config.json` e `templates/`, nada fixo no código)

- Duração do corte: mínimo `clip_min_seconds` (20), ideal `clip_target_seconds` (25–45), **sem máximo**
  (`clip_max_seconds` null): passa de 59s quando a história pede. Sem enrolação no fim.
- **Recuo antes do pico:** começar `pre_roll_seconds` (15s) antes do pico de áudio/chat, porque a
  reação vem depois do fato. Depois aparar para a primeira frase/ação forte (gancho primeiro).
- **Blocos de 1 hora** (`chunk_minutes`) com 5 min de sobreposição (`chunk_overlap_minutes`) via
  `download.py --section`; descartar cortes repetidos na sobreposição. Em lives longas, 1 a 3 cortes
  por bloco, sem forçar número. O usuário costuma pedir "N shorts por hora".
- **Bloco por bloco, sem esperar o usuário** (`auto_next_block`): termine o bloco 1 (baixar, transcrever com tiny, ler em blocos de 10 min,
  olhar frames, retranscrever candidatos com small, escolher, renderizar), **entregue os cortes dele com o preview** e então
  siga sozinho para o bloco 2, e assim até o fim do vídeo. Enquanto um bloco transcreve ou renderiza, baixe
  o próximo (download só usa rede). Bloco sem momento bom entrega menos cortes (não force). Avise em uma
  linha a cada bloco pronto, com o caminho da pasta.
- **No máximo 2 jobs pesados ao mesmo tempo** (`max_parallel_jobs`: transcrição/render). Download
  pode rodar em paralelo à vontade.
- **Chat sempre** (`download_chat`): YouTube via yt-dlp; Twitch via `tools/TwitchDownloaderCLI` (instale uma vez com `python scripts/install_twitch_cli.py`).
- Download por seção corta por cópia de stream (sem recodificar), 8 fragmentos em paralelo:
  1 hora baixa em minutos.

## Identidade visual (referência de tudo)

- **Logo oficial: "RSK CORTES"** (`assets/logo.png`: letras RSK com cidade ao pôr do sol, coroa, palmeiras,
  claquete; fundo preto). No card entra **redonda** (`circle: true`) com margem preta (`pad` 0.18, tamanho 190),
  para a arte aparecer inteira sem cortar as pontas do V. Logo antiga "Cortes GTA 6": `assets/logo_gta6_loucuras.png`.
- **Fontes** (estáticas, em `fonts/`, apontadas direto nos templates): Montserrat Black (gancho,
  subgancho, etiqueta do card, título do `nocam`) e Poppins ExtraBold (legenda). Aprovadas pelo usuário.
- **Template ativo `templates/cam.json` = "RSK CORTES, cores da logo"**: caixa escura em degradê, borda neon
  azul (#4B5BFF) → roxo (#C02BE8) → rosa (#FF3DCB) → laranja (#FF9A3C) com brilho, logo à esquerda, gancho rosa
  neon (#FF4FD8), subgancho azul-gelo (#CFE3FF), etiqueta do canal embaixo (degradê roxo→rosa, borda branca).
  Backup do visual anterior: `templates/cam_gta6_loucuras.json`; laranja antigo: `cam_laranja.json`.
- **Nome do canal** (`channel_name`): **RSK CORTES** (definido pelo usuário).
- **Legenda do `cam`:** pequena-média (tamanho 69), palavra em destaque rosa (#FE5CCD), posicionada
  `gap` px (30) acima do topo do card (`captions.anchor: "above_card"`). Nunca duas legendas ao mesmo tempo.

## Passo -1 — Receber o link e fazer as perguntas (o usuário só manda o link)

Quando o usuário mandar só o link, **não comece a baixar**. Primeiro olhe o vídeo sem baixar
(`python -m yt_dlp --skip-download --print "%(title)s | %(uploader)s | %(duration_string)s | %(is_live)s" <URL>`;
no YouTube veja também se há `heatmap` e legenda/chat) e depois use a ferramenta de perguntas
(AskUserQuestion), **uma única rodada, no máximo 2 perguntas**, só sobre o que você não consegue
descobrir sozinho. Escreva as perguntas em português simples, com um resumo do vídeo (título, canal,
duração), e deixe a primeira opção como a recomendada:

1. **Quantos shorts?** (ex.: 2 por hora, 5 no total). Padrão: 2 por hora de vídeo.
2. **Qual trecho?** Só para vídeos de 2h ou mais (opções: primeira hora, um intervalo que ele digitar,
   o vídeo inteiro por blocos de 1 hora). Em vídeo curto, não pergunte.
Não pergunte sobre permissão de repostagem (o usuário já disse que tem) nem sobre nome do canal e card:
use sempre o que está em `templates/cam.json`/`nocam.json` e na memória (o usuário vai fixar o padrão).

Também não pergunte o que dá para decidir sozinho: se tem webcam (veja os quadros), se há legenda gravada, qual
modelo de transcrição, o tamanho da legenda, as cores. Depois das respostas, avise em uma linha o que vai
fazer e quanto deve demorar, e comece. Sem resposta, use os padrões e diga quais usou.

## Passo 0 — Conferir instalação (primeira vez)

`python scripts/check_setup.py` (ffmpeg, yt-dlp, faster-whisper, numpy, pillow). Instale o que faltar.

## Passo 1 — Baixar

```
python scripts/download.py "<URL>" --out work/<id> [--section 00:00:00-01:00:00]
```
Gera `source.mp4` (até 1080p), `info.json`, `chat.json` e, com `--section`, `section.json` (deslocamento).
Lives de 3h+: pergunte qual trecho (ou use blocos de 1 hora). Login/idade: veja `C:\cortes\COMO-USAR.md`
(YouTube usa cookies copiados e plugin de PO token).

## Passo 2 — Transcrever o bloco inteiro com o modelo tiny (rápido)

```
python scripts/transcribe.py work/<id>/source.mp4 --model tiny --beam 1 --language pt
```
A escolha dos cortes parte da **transcrição completa**, não dos picos. Gera `transcript.json`/`transcript.txt`
(modelo `tiny` por padrão, `transcribe_fast` no `config.json`: precisão baixa, serve só para ler e achar
candidatos, e o `small` refaz os escolhidos no passo 3c). Se o texto vier ilegível a ponto de esconder piadas,
suba para `base` no config. Dica: enquanto transcreve o bloco atual, o download do próximo pode rodar junto.

## Passo 3 — Ler tudo em blocos de 10 minutos e listar candidatos

```
python scripts/read_blocks.py work/<id>              # lista os blocos
python scripts/read_blocks.py work/<id> --block N    # lê o bloco N (10 min)
```
**Leia todos os blocos, do primeiro ao último**, sem pular nem ler só ao redor dos picos. Procure:
piadas, reviravoltas, discussões, situações inesperadas, histórias engraçadas (com desfecho) e reações
fortes. Anote cada candidato (início, fim, por que é bom) numa lista `cands.json`:
`[{"id":1,"start":"00:08:05","end":"00:08:40","why":"..."}]`. Seja generoso aqui (cerca de 4x o número
de shorts pedidos); a seleção final vem depois.

**Apoio, não filtro:** rode `python scripts/find_hype.py work/<id> --top 15` (áudio, chat, "clipa",
movimento) e use só para (a) conferir o chat/áudio dos seus candidatos e (b) achar trechos que a leitura
deixou passar. Pico sem graça na leitura é descartado; candidato bom sem pico **fica**. Palavras mais
frequentes de um momento: `find_hype.py work/<id> --words 00:08:05-00:08:35`.

## Passo 3b — Olhar os frames dos candidatos

```
python scripts/extract_frames.py work/<id> --candidates work/<id>/cands.json --frames 6
```
Gera `work/<id>/frames/cand<N>.jpg` (folha com 6 quadros). **Abra e analise as imagens** (Read): pega
momentos visuais sem fala (batida, explosão, fuga, susto, cena absurda) e confirma ou derruba o candidato.
Se a leitura do bloco trouxe pouca coisa, extraia frames também de picos do `find_hype.py` que ficaram sem fala.

## Passo 3c — Retranscrever só os candidatos com o modelo small

```
python scripts/transcribe.py work/<id>/source.mp4 --candidates work/<id>/cands.json --pad 10 --model small --language pt
```
O `small` substitui, dentro de `transcript.json`, só os trechos candidatos (palavras precisas para a legenda
e para ajustar `start`/`end` em fronteiras de palavra). O resto continua com o `tiny`. Se o Aspire 16 tiver GPU NVIDIA (CUDA é
detectada sozinha), dá para usar `small` na transcrição inteira.

## Passo 4 — Escolher os cortes e escrever `clips.json`

Releia os candidatos já com o `small` e com os frames na cabeça (use `references/viral-rules.md`).
Escolha os melhores pela história/graça, não pelo volume. Compare com o chat. Descarte o que não faz
sentido sem contexto.
Cada corte: começa no gancho, termina logo após o desfecho.

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
    "reason": "piada + reviravolta; chat em KKKK",
    "score": 9
  }
]
```
- `style`: `"cam"` (com webcam) ou `"nocam"` (sem). `hook` = linha 1 do card, `subhook` = linha 2
  (máx. ~5 palavras cada, sem emoji; a caixa alta vem do template). `title` só vale para o kit de postagem.
- Ajuste `start`/`end` em fronteiras de palavra. Opcionais por corte: `"captions": false`, `"cam": [x,y,w,h]`.

## Passo 4b — Ver o vídeo e escolher o estilo

`python scripts/make_shorts.py work/<id> --snapshot` → `snapshot.jpg` (6 quadros) e `snapshot_1..6.jpg`.
Olhe e decida:
1. **Tem webcam?** Sim → `cam`; estime o retângulo da webcam em frações `x,y,w,h` e confira com
   `make_shorts.py work/<id> --cam x,y,w,h --snapshot` (caixa vermelha). Ele deve ficar **dentro da webcam**
   (o recorte só encolhe, nunca sai dela), sem barras de overlay como "último sub". Fica salvo em `setup.json`.
   Não → `nocam`.
2. **Legenda gravada na imagem?** Sim → `--burned-subs` (salvo em `setup.json`): sem legenda palavra por palavra.

## Passo 5 — Renderizar

`python scripts/make_shorts.py work/<id> [--only 1,2] [--out-dir DIR] [--template-dir DIR]`

- **`cam`:** topo 768px = webcam preenchendo a largura; baixo 1152px = gameplay recortada para preencher a
  largura; o card (caixa do gancho + etiqueta do canal) **centrado na divisão (y=768)** durante o vídeo todo;
  legenda pequena acima do card.
- **`nocam`** (layout "stack", chave `stack` em `nocam.json`): fundo = vídeo ampliado e desfocado (em cima
  e embaixo); **logo RSK redonda com anel rosa→laranja centralizada no topo**, **gancho logo abaixo em
  degradê GTA (rosa→laranja) com contorno preto e brilho**, sem caixa; gameplay no meio sem zoom
  (`zoom` 1.0); legenda rosa embaixo (y 1420). Título branco antigo: `templates/nocam_antigo.json`.
- **Qualidade da webcam:** o recorte é esticado (~2,9x), então o template usa escalonamento Lanczos + leve
  nitidez (`layout.scale_flags`, `layout.cam_sharpen`). O limite real é a resolução da webcam na origem.
- Saída sempre H.264 yuv420p 30fps + áudio AAC normalizado; o script confere cada arquivo e falha se não bater.
- O card aceita no template: degradê, imagem de fundo escurecida, borda em degradê, brilho, brilho no texto,
  logo (redonda ou arredondada), etiqueta em cima ou embaixo. Tudo opcional e configurado no JSON.
- Tempo no PC antigo (i5-2400, será trocado pelo Aspire 16: medir de novo): render de um corte de ~28s leva ~40-50s; achar os momentos de 1h ~3,5 min.

## Passo 6 — Conferir e entregar

1. `make_shorts.py work/<id> --preview` → `shorts/preview.jpg` (3 quadros por short). Confira legenda
   legível, recorte da webcam, card sem cobrir rosto.
2. `shorts/posting-kit.md`: por short, título (<70 caracteres), descrição curta, 5–8 hashtags e qual postar primeiro.
3. Diga ao usuário onde está a pasta e quais postaria primeiro. No Windows, abra imagens com
   `Start-Process <png>`; abrir `.mp4` por Start-Process falha, peça para abrir pelo Explorer.

## Gameplay solo (lançamento do GTA 6, 19/11/2026) e calibração

- **Gameplay solo não tem chat nem webcam:** o `find_hype.py` perde o sinal principal. Nesse caso a leitura da
  transcrição (se o usuário narra) e os frames viram a fonte principal de candidatos (passos 2 a 3b). Use `nocam`.
- **Música do rádio do jogo** dá claim/mute: pular trechos com música licenciada alta (ver `viral-rules.md`).
- **Capacidade (estimativa, medir no Aspire 16 quando chegar):** com qualidade, ~10-15 shorts por hora de
  trabalho no Aspire e ~6-10 no PC antigo (i5-2400); o limite é escolher e conferir, não renderizar. Contar ~4
  bons cortes por hora de gameplay gravado (50-100 shorts = 10-25 h de material). Não force número.
- **Teste cego de calibração (a pedido do usuário):** ele escolhe uma live inteira e anota os cortes que faria
  (início, fim, motivo, e o que descartou de propósito) **sem me mostrar**. Eu rodo o fluxo completo sobre o
  link, entrego os meus, e comparamos: coincidências, só dele, só meus, e o porquê de cada diferença. Os
  padrões que ele explicar vão para `references/viral-rules.md` e para a memória. Repetir com outra live.
- **Postagem:** espalhar os shorts ao longo dos dias em vez de postar tudo de uma vez; os melhores primeiro.
- **Ideia pendente:** ler marcadores de capítulo do OBS (ou "clipa" falado) como candidatos de maior peso.

## Como o usuário edita depois

- **Texto do gancho / tempo do corte:** pedir a você, ou editar `hook`, `subhook`, `start`, `end` em
  `work/<id>/clips.json` e rodar `make_shorts.py work/<id> --only N`.
- **Visual** (cores, tamanhos, posição, logo, nome do canal): `templates/cam.json` ou `nocam.json`.
- Antes de sobrescrever shorts já aprovados, guarde cópia (ex.: `shorts_laranja_antigo/`).

## Notas

- O usuário disse ter permissão para repostar os cortes que pede (ex.: alanzoka); não pergunte de novo.
- Tudo roda localmente, exceto o download. Nada é enviado para fora.
- Preferências do usuário e identidade do canal também estão na memória do Claude (pasta do projeto).
