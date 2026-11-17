# Especificação: skill de cortes "lisinha"

Entregue este arquivo ao Claude Code, dentro de `C:\cortes`, junto com o `viral-rules.md` novo.
Antes de começar: faça um commit do estado atual da skill. No fim: rode o teste da seção 6 e mostre o
`git diff --stat` e um resumo do que mudou.

Skill: `C:\Users\User\.claude\skills\gta-clipper-skill\`. Tudo que for valor ajustável vai para `config.json`;
nada de caminho ou número fixo no código.

---

## 1. Decisões do usuário (implementar exatamente assim)

### 1.1 Sem chat do YouTube
- `download.py`: não baixar chat quando o link for do YouTube. Twitch continua baixando chat
  (TwitchDownloaderCLI).
- `find_hype.py`: remover a leitura do formato de chat do YouTube (uma mensagem JSON por linha).
  Com isso, `--words` em vídeo do YouTube mostra só a fala (hoje ele quebra com chat do YouTube).

### 1.2 Mapa de "mais repetidos" do YouTube como sinal
- `download.py`: salvar o `heatmap` do yt-dlp (quando existir) em `heatmap.json`, com tempos absolutos
  do vídeo original.
- `find_hype.py`: usar o heatmap como sinal de apoio (peso em `config.json` → `hype.weights.heatmap`),
  convertendo para o tempo do arquivo com o offset do `section.json`. Sem heatmap, segue sem ele.

### 1.3 Idioma detectado automaticamente
- Remover todo `--language pt` fixo (SKILL.md, config.json, mensagens dos scripts).
- Nova detecção: pegar 3 a 5 trechos de ~30 s espalhados pelo meio do vídeo (evitar começo e fim),
  detectar com o modelo `tiny` e usar o idioma que mais aparecer. Gravar em `work/<id>/lang.json`.
  As transcrições seguintes usam esse idioma.

### 1.4 Vídeo gringo (idioma diferente de pt)
- A legenda do short sai traduzida para português do Brasil.
- Tradução feita pelo Claude, por grupo de legenda (frase), mantendo o tempo do grupo original.
  O destaque palavra por palavra é distribuído proporcionalmente ao tamanho das palavras dentro do tempo do grupo.
- Depois de escolher os cortes, o Claude revisa a tradução de cada corte escolhido pensando na cena
  (gíria, ironia, palavrão soando natural em português). A tradução revisada fica em `clips.json`
  (ex.: campo `captions_pt` por corte) e é ela que o `make_shorts.py` usa.
- Gancho, subgancho, título e hashtags sempre em português.

### 1.5 Offset do trecho medido de verdade
- Com `--section`, o corte é por cópia de stream e o arquivo começa no keyframe anterior.
  Depois do download, medir o início real (ffprobe: start_time/primeiro pts do arquivo
  em relação ao vídeo original) e gravar em `section.json` o offset REAL, não o pedido.
  Chat da Twitch e heatmap usam esse offset.

### 1.6 Shorts com 10 segundos extras antes e depois
- `config.json`: `pad_before: 10`, `pad_after: 10`.
- `make_shorts.py` renderiza o short completo (card, legenda, layout) de `start - pad_before` até
  `end + pad_after`, respeitando o começo e o fim do vídeo.
- A legenda cobre os extras também (a retranscrição com `small` já usa margem de 10 s; garantir que a
  margem da retranscrição seja ≥ pad).
- No `posting-kit.md`, para cada short: "corte sugerido no arquivo: 0:10 a 0:47" (tempo dentro do arquivo).

### 1.7 Ganchos
- O Claude escreve gancho e subgancho e renderiza direto (sem esperar aprovação).
- No fim de cada bloco, mostrar a lista: arquivo, gancho/subgancho, corte sugerido.
- Para trocar, o usuário manda "corte N: GANCHO / SUBGANCHO"; o Claude edita o `clips.json` e
  renderiza só aquele (`--only N`).
- O modo bloco por bloco (`auto_next_block`) continua rodando sozinho.

### 1.8 Live ainda no ar
- Twitch: se o link for de canal (`twitch.tv/nome`) e o canal estiver ao vivo, achar o VOD da live atual
  (`twitch.tv/nome/videos`, o mais recente marcado como ao vivo) e usar o link do VOD. Se não houver VOD,
  avisar e parar. Nunca ficar gravando até a live acabar.
- YouTube: se a live estiver no ar, baixar só o que já passou até agora (bloco fechado) e cortar isso.
  Avisar que a live ainda está rolando. Desligar `live_from_start` para vídeos que não são live.
- Colocar essas regras no SKILL.md (Passo -1).

### 1.9 Resultados no Notion (automático)
- O Claude Code do usuário tem o MCP do Notion conectado (`claude mcp add --transport http --scope user
  notion https://mcp.notion.com/mcp`, depois `/mcp` para autorizar).
- `config.json` → `notion`:
  - `resultados_data_source`: `collection://41b43190-4def-819e-87da-000b0257adc4` (base "Resultados dos Cortes")
  - `canais_data_source`: `collection://41a43190-4def-8125-a1bb-000b848717e9` (base "Canais para Cortes")
- Novo passo no fim do SKILL.md: para cada short renderizado, criar uma linha em "Resultados dos Cortes":
  - Gancho (título), Canal (relação com a página do canal na base de canais; se o canal não existir lá,
    criar com Status "Cortando" e a Plataforma certa), Data do corte (hoje), Link do vídeo,
    Horário no original (ex.: 01:12:05 a 01:12:41, em tempo absoluto do vídeo), Corte sugerido no arquivo,
    Arquivo (caminho do .mp4), Estilo (cam/nocam), Tipo de momento (Reação, Fail, Jogada, Piada, História,
    Discussão), Idioma de origem (PT/Gringo), Status "Renderizado".
  - Na base de canais: "Cortes feitos" +1 e "Último corte" = hoje.
  - Views 24h, Views 7d, Retenção %, Postado em, Data da postagem e Observação ficam para o usuário.
- Se trocar o gancho de um corte e renderizar de novo, atualizar a mesma linha (não criar outra).
- Se o Notion não estiver disponível, renderizar normal e avisar em uma linha (não travar).
- Análise: quando o usuário pedir, ler a base, mas só apontar padrões com 20 ou mais linhas com views
  preenchidas.

---

## 2. Regras de corte

- Substituir `references/viral-rules.md` pelo arquivo novo (em português) que acompanha esta espec.

---

## 3. Faxina de documentação

- README.md: reescrever para o fluxo atual (tiny no vídeo todo → leitura em blocos → frames →
  small nos candidatos → render com ±10 s → Notion). Em português.
- `config.json`: remover `transcribe_windows` (fluxo antigo). Adicionar as chaves novas
  (pad_before, pad_after, heatmap, detecção de idioma, notion, caminhos da seção 4).
- `find_hype.py`: remover a mensagem final que sugere `--windows ... --language pt`.
- SKILL.md: revisar inteiro contra estas decisões; nada contraditório, nada do fluxo antigo.
  Mensagens de progresso em português.
- CLAUDE.md da skill: manter curto e alinhado com o SKILL.md.

---

## 4. Instalação e portabilidade (para o notebook novo)

- `requirements.txt`: adicionar `bgutil-ytdlp-pot-provider`, `yt-dlp-ejs` e `av>=14,<17`.
- `check_setup.py`: além do que já confere, conferir Node.js, o gerador do PO token e o
  TwitchDownloaderCLI, dizendo exatamente o comando para instalar o que faltar.
- Mover para o `config.json` os caminhos fixos: `cookies_master` (hoje `C:\cortes\cookies-master.txt`)
  e `pot_script` (gerador do bgutil). Variável de ambiente continua podendo sobrescrever.

---

## 5. Não mexer

- Visual aprovado: `templates/cam.json` (RSK CORTES), `templates/nocam.json`, fontes Montserrat Black
  e Poppins ExtraBold em `fonts/`, logo em `assets/logo.png`.
- Uso de cookies sempre por cópia temporária do arquivo master.
- Saída H.264 / yuv420p / 30 fps / AAC com verificação.
- `.gitignore` (cookies, work/, vídeos, executáveis fora do git).

---

## 6. Teste final

1. `check_setup.py` → tudo OK.
2. Um vídeo do YouTube curto em português (5 a 10 min): baixar com `--section` de 3 minutos,
   conferir `section.json` (offset real), `lang.json` = pt, heatmap (se tiver), 1 short `nocam`
   com ±10 s, linha criada no Notion.
3. Um VOD da Twitch em inglês (trecho de 5 min): chat baixado, `lang.json` = en, legenda em
   português, 1 short `cam`, linha no Notion com Idioma "Gringo".
4. Trocar o gancho de um dos shorts e conferir que só ele foi renderizado e a linha do Notion foi atualizada.
5. Mostrar o preview.jpg dos dois testes.
