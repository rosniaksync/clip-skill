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

**Novidades do jogo também valem (pedido do usuário em 18/11/2026):** loja, academia, barbearia, celular/apps,
gráfico, física, detalhe que ninguém viu, mecânica nova, NPC fazendo algo realista. Basta o streamer mostrar e
reagir um pouco surpreso ("olha isso", "que detalhe", "não acredito que dá pra..."). Esse tipo é o mais
buscado no lançamento: gente que não tem o jogo quer ver "como é X no GTA 6".

## Gancho (os 2 primeiros segundos decidem tudo)

- O corte começa no gancho (ver "Início e fim perfeitos" abaixo). O arquivo é o corte exato, postado sem
  editar: não há mais ajuste fino no editor.
- Se o desfecho está no fim, comece na frase mais dramática e deixe a construção rolar, cortando o
  máximo possível da preparação.
- O texto do gancho cria curiosidade, não descreve: "ELE NÃO ESPERAVA ISSO" é melhor que
  "Momento engraçado no GTA". Sem emoji no card. No máximo ~5 palavras por linha.
- **Nada de gancho genérico** ("ELE NÃO QUERIA PROBLEMA", "ESSE GTA É CINEMA"). Use o detalhe concreto e
  estranho do corte, o que faz a pessoa pensar "como assim?". Fórmulas que funcionam:
  - pergunta de quem não tem o jogo: "COMO É A ACADEMIA NO GTA 6 ????", "DÁ PRA CORTAR O CABELO NO GTA 6 ????"
  - detalhe surpreendente: "O GTA 6 TEM ISSO E NINGUÉM PERCEBEU", "ATÉ A CAIXA DE PAPELÃO SE MEXE NO GTA 6"
  - promessa x resultado: "ELE JUROU QUE IA ANDAR NA MORAL… DUROU 10 SEGUNDOS"
  - número/absurdo específico: "PULOU DE TRAILER DE UMA PONTE QUEBRADA COM 5 MIL NO BOLSO"
  - a frase dele entre aspas, quando é forte: "\"OS CARAS TÃO DE COLETE, VIADO\""
- **Sempre 3 opções de gancho por corte**: a melhor vai no vídeo (`hook`), as outras 2 em `hook_alt`
  (lista). No Notion vão em "Outros ganchos" junto com "O que acontece" (1 frase do que se vê no vídeo), para o
  usuário trocar o gancho sem ter que assistir. Ele responde "07 → 2" e eu renderizo de novo só esse short
  (`make_shorts.py --only N`) e troco o arquivo.

## Duração e final

- A partir de 20 segundos, sem máximo fixo (ver `config.json`). Abaixo de 30 segundos tende a ser
  reassistido mais; passe de 59 segundos só quando a história pede. Nunca encha linguiça.
- Termine no desfecho ou na reação (ver "Início e fim perfeitos" abaixo).

## Início e fim perfeitos

O short é postado direto, sem editar. Confira cada corte com `scripts/check_cut.py work/<id> --clip N`
(palavras, volume a cada 0,1 s, trocas de cena e frames do início e do fim) antes de renderizar.

### Início
- Começa no gancho: a primeira frase ou ação que já prende. Nunca em cumprimento, "então", "tipo", silêncio,
  menu ou loading.
- Se precisar de contexto, usa só a frase mínima (até ~3 s) antes do gancho.
- Corta em fronteira de palavra: início = começo da primeira palavra menos 0,15 s. Nunca no meio de uma palavra
  ou de uma sílaba.
- Momento visual (batida, fuga, susto): começa 0,5 a 1 s antes da ação, conferido nos frames.
- Não começa num corte de câmera ou transição.

### Fim
- Termina 0,3 a 0,8 s depois da última palavra do desfecho ou da reação.
- Se termina em risada ou grito, corta quando o som começa a cair, nunca no meio do pico.
- Nada depois do desfecho: sem "bom", "enfim", "chat", troca de assunto.
- Quando der, prefere um final que emende com o começo (loop).
- Se houver troca de cena ou corte de edição logo depois (comum em VOD editado do YouTube), o fim fica antes
  dela, mesmo que a folga depois da última palavra fique menor que 0,3 s.

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
