---
name: gta-clipper-skill
description: Transforma qualquer live ou vídeo longo (YouTube, Twitch VOD, Kick etc.) em shorts verticais prontos para postar (1080x1920, card de gancho, legenda palavra por palavra). Use quando o usuário colar um link de live/vídeo e pedir shorts, cortes, reels, clips, ou "is stream se viral shorts banao".
---

# Live → Shorts virais

O usuário cola o link de uma live. Você baixa, acha os melhores momentos, transcreve só o necessário,
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
- **No máximo 2 jobs pesados ao mesmo tempo** (`max_parallel_jobs`: transcrição/render). Download
  pode rodar em paralelo à vontade.
- **Chat sempre** (`download_chat`): YouTube via yt-dlp; Twitch via `tools/TwitchDownloaderCLI` (instale uma vez com `python scripts/install_twitch_cli.py`).
- Download por seção corta por cópia de stream (sem recodificar), 8 fragmentos em paralelo:
  1 hora baixa em minutos.

## Identidade visual (referência de tudo)

- **Logo oficial:** `assets/logo.png` (arte quadrada "Cortes GTA 6": claquete, pôr do sol, palmeiras,
  carro). No card ela entra **recortada em círculo**. A versão circular antiga: `assets/logo_antiga_circulo.png`.
- **Fontes** (estáticas, em `fonts/`, apontadas direto nos templates): Montserrat Black (gancho,
  subgancho, etiqueta do card, título do `nocam`) e Poppins ExtraBold (legenda). Aprovadas pelo usuário.
- **Template ativo `templates/cam.json` = "synthwave + laranja na borda"** (opção 08 do catálogo): caixa
  escura em degradê, borda neon roxo→rosa→laranja com brilho, logo redonda à esquerda, gancho rosa neon
  (#FF4FD8), subgancho azul-gelo (#CFF6FF), etiqueta do canal embaixo do card (degradê rosa→laranja,
  borda branca). Backup do visual laranja antigo: `templates/cam_laranja.json`.
- **Catálogo de opções de card** (o usuário ainda está escolhendo): `C:\cortes\cards\` (com logo) e
  `C:\cortes\cards\sem_logo\` (sem logo): 8 cards cada, folha `TODOS_OS_CARDS.png`, uma imagem por card
  e `templates/` com o JSON de cada um. Cópia dos JSONs em `templates/opcoes/`. **Para aplicar o card N:**
  copie `templates/opcoes/<com_logo|sem_logo>/NN-..._cam.json` para `templates/cam.json`, ponha o nome do
  canal em `channel_name` e renderize de novo.
- **Nome do canal** (`channel_name` no `cam.json`): o usuário ainda não decidiu. Hoje está "GTA6 LOUCURAS".
  Pergunte antes de entregar versão final.
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

## Passo 2 — Achar os momentos ANTES de transcrever (caminho rápido, padrão)

```
python scripts/find_hype.py work/<id> --top 10
```
Funciona **sem transcrição**. Sinais (pesos e listas em `config.json` → `hype`):
- **Principais:** volume do áudio (picos de grito/risada) e chat (volume + reações `kk`, `lul`, `omegalul`...).
- **"clipa" no chat pesa mais** (`clip_call_words`): é o público apontando o momento. O reforço cresce com
  o número de mensagens na janela (`clip_calls_full_at`), para uma só não dominar.
- **Palavras são só reforço** (peso baixo): o modelo pode escrever palavrão diferente ou cortar a palavra.
- **Filtro de gameplay:** janelas com imagem parada (menu, carregando) ficam de fora
  (`motion_gate_percentile`, 15%).
- **Texto normalizado antes de comparar:** minúsculo, sem acento, letras repetidas reduzidas
  (`caraaaalho` → `caralho`, `kkkkkkk` → `kk`).
- Palavras mais frequentes de um momento (fala + chat): `find_hype.py work/<id> --words 00:08:05-00:08:35`.

## Passo 3 — Transcrever só os melhores trechos

```
python scripts/transcribe.py work/<id>/source.mp4 --windows work/<id>/hype.json --top 8 --pad 20 --model small --language pt
```
`--top` = cerca de 4x o número de shorts desejados (sobra opção de escolha; se nada prestar, transcreva
mais 4). O modelo carrega uma vez, os trechos são unidos e mesclados em `transcript.json`/`transcript.txt`.
Estenda um trecho com `--range S-E`. Em PC rápido ou com GPU (CUDA é detectada sozinha), pode transcrever
tudo (`--model small`). Plano B lento: transcrição da hora toda com `--model base --beam 1`, depois refinar
os cortes escolhidos com `--model small --range S-E` (a legenda precisa de palavras precisas).

## Passo 4 — Escolher os cortes e escrever `clips.json`

**Leia você mesmo** a transcrição dos trechos (use `references/viral-rules.md`): procure história com
desfecho, piada, reação forte. Compare com o chat. Descarte pico sem graça.
Cada corte: começa no gancho, termina logo após o desfecho, faz sentido sem contexto.

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
    "reason": "pico de áudio + chat em KKKK",
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
- **`nocam`:** fundo = vídeo ampliado e desfocado; meio = gameplay com leve zoom; título branco, caixa alta,
  contorno preto, 2 linhas, no topo; legenda na faixa desfocada de baixo.
- **Qualidade da webcam:** o recorte é esticado (~2,9x), então o template usa escalonamento Lanczos + leve
  nitidez (`layout.scale_flags`, `layout.cam_sharpen`). O limite real é a resolução da webcam na origem.
- Saída sempre H.264 yuv420p 30fps + áudio AAC normalizado; o script confere cada arquivo e falha se não bater.
- O card aceita no template: degradê, imagem de fundo escurecida, borda em degradê, brilho, brilho no texto,
  logo (redonda ou arredondada), etiqueta em cima ou embaixo. Tudo opcional e configurado no JSON.
- Tempo neste PC (i5-2400): render de um corte de ~28s leva ~40-50s; achar os momentos de 1h ~3,5 min.

## Passo 6 — Conferir e entregar

1. `make_shorts.py work/<id> --preview` → `shorts/preview.jpg` (3 quadros por short). Confira legenda
   legível, recorte da webcam, card sem cobrir rosto.
2. `shorts/posting-kit.md`: por short, título (<70 caracteres), descrição curta, 5–8 hashtags e qual postar primeiro.
3. Diga ao usuário onde está a pasta e quais postaria primeiro. No Windows, abra imagens com
   `Start-Process <png>`; abrir `.mp4` por Start-Process falha, peça para abrir pelo Explorer.

## Como o usuário edita depois

- **Texto do gancho / tempo do corte:** pedir a você, ou editar `hook`, `subhook`, `start`, `end` em
  `work/<id>/clips.json` e rodar `make_shorts.py work/<id> --only N`.
- **Visual** (cores, tamanhos, posição, logo, nome do canal): `templates/cam.json` ou `nocam.json`.
- Antes de sobrescrever shorts já aprovados, guarde cópia (ex.: `shorts_laranja_antigo/`).

## Notas

- O usuário disse ter permissão para repostar os cortes que pede (ex.: alanzoka); não pergunte de novo.
- Tudo roda localmente, exceto o download. Nada é enviado para fora.
- Preferências do usuário e identidade do canal também estão na memória do Claude (pasta do projeto).
