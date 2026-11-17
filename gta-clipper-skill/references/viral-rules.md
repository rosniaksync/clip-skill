# O que faz um momento de live virar um bom short

Use estas regras para ranquear os candidatos. Um corte precisa de pelo menos 2 delas para valer a pena.

## Como achar os candidatos (processo)

1. Transcreva o bloco inteiro com o modelo rápido (`tiny`) e leia TUDO em blocos de 10 minutos
   (`read_blocks.py`), não só em volta dos picos. Piadas e histórias boas costumam ser contadas com calma.
2. Durante a leitura, procure: piadas, reviravoltas, discussões, situações inesperadas, histórias engraçadas
   com desfecho e reações fortes.
3. Extraia os frames de cada candidato (`extract_frames.py`) e olhe as imagens: alguns dos melhores momentos
   são visuais e sem fala (batida, fuga, cena absurda, susto).
4. Retranscreva só os candidatos com o `small` e então escolha os cortes finais.
5. Os sinais do `find_hype.py` (áudio, chat da Twitch, "clipa", mapa de mais repetidos do YouTube, movimento)
   são apoio. Nunca decidem sozinhos. Pico alto sem graça na leitura é descartado; história boa sem pico fica.

## Abertura do jogo (lançamento do GTA 6 e outros lançamentos)

- A abertura do jogo (primeira tela, logo, primeira cena) é **sempre candidata em toda live**, mesmo com menu
  ou tela de carregamento na imagem. É a exceção à regra de descartar menu/loading.
- O corte começa na **reação** do streamer, não na espera do carregamento.
- Se a música do jogo estiver alta, faça o corte mesmo assim e avise no kit:
  "música do jogo alta: risco de som mudo" (campo `aviso` do corte).
- **No máximo um short de abertura por live.**

## Tipos de momento que funcionam (do melhor para o pior)

1. Reação emocional forte: grito, risada que não para, raiva, choque. Pico de áudio com a voz do streamer.
2. Jogada absurda: fuga no último segundo, manobra impossível, timing perfeito. O chat costuma explodir.
3. Fail e karma: o plano dá errado, arrependimento instantâneo, "NÃÃÃO".
4. Interação engraçada: zoeira com outro jogador, NPC fazendo besteira, doação ou mensagem inesperada.
5. História com desfecho: começo, virada e final engraçado em até ~45 segundos.
6. Frase marcante: algo que as pessoas vão citar ou discutir nos comentários.

## Gancho (os 2 primeiros segundos decidem tudo)

- O corte sugerido começa no pico ou 1 segundo antes. Nunca começa em cumprimento, "então, tipo...",
  silêncio, menu ou tela de carregamento. (O arquivo final ainda leva 10 segundos extras antes e depois,
  para o ajuste fino no editor.)
- Se o desfecho está no fim, comece na frase mais dramática e deixe a construção rolar, cortando o
  máximo possível da preparação.
- O texto do gancho cria curiosidade, não descreve: "ELE NÃO ESPERAVA ISSO" é melhor que
  "Momento engraçado no GTA". Sem emoji no card. No máximo ~5 palavras por linha.

## Duração e final

- A partir de 20 segundos, sem máximo fixo (ver `config.json`). Abaixo de 30 segundos tende a ser
  reassistido mais; passe de 59 segundos só quando a história pede. Nunca encha linguiça.
- Termine no desfecho ou na reação, 0,3 a 0,8 segundo depois da última palavra.
- Um final que emenda com o começo (loop) aumenta as reassistidas.

## Vídeo gringo

- A legenda sai traduzida para português. Depois de escolher os cortes, revise a tradução de cada um
  pensando no contexto da cena: gíria, ironia e palavrão precisam soar natural em português, não literal.
- Gancho, título e hashtags sempre em português.

## Descartar

- Momentos que dependem de contexto de antes na live.
- Silêncio longo, menu, AFK, tela de carregamento, intervalo, "já volto" (exceto a abertura do jogo, ver acima).
- Música com direitos autorais tocando alto, inclusive o rádio do jogo (gera claim ou som mudo). Exceção: a
  abertura do jogo, que é cortada mesmo assim, com o aviso no kit.
- Qualquer dado pessoal na tela (endereço, telefone, mensagens privadas).

## Título e hashtags (kit de postagem)

- Título = gancho + 1 emoji + nome do streamer. Menos de 70 caracteres.
- Hashtags: jogo (#gta6 #gtavi), formato (#shorts #cortes), nome do streamer e 1 ou 2 amplas
  (#gameplay #games). De 5 a 8 no total.
