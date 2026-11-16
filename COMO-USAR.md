# Download do YouTube: o que fazer quando os cookies expirarem

## Como está configurado

O `download.py` da skill (`C:\Users\User\.claude\skills\gta-clipper-skill\scripts\download.py`) sempre:

- usa o **Node** como runtime JavaScript (resolve os desafios de assinatura do YouTube);
- usa o plugin **bgutil-ytdlp-pot-provider** em modo script (gera o PO token sem servidor).
  O gerador fica em `C:\Users\User\bgutil-ytdlp-pot-provider\server\build\generate_once.js`;
- tenta baixar **sem cookies** primeiro;
- se o vídeo pedir login ou verificação de idade, usa uma **cópia temporária** de
  `C:\cortes\cookies-master.txt` e apaga a cópia no fim. O original nunca é aberto pelo yt-dlp,
  porque o yt-dlp reescreve (e acaba invalidando) o arquivo de cookies que recebe;
- baixa a **melhor qualidade até 1080p** (vídeo + áudio, saída em MP4).

Uso básico:

```
python C:\Users\User\.claude\skills\gta-clipper-skill\scripts\download.py "<URL>" --out work\<id>
```

Opções úteis: `--max-height 720`, `--section 00:10:00-00:40:00`, `--no-chat`,
`--cookies <outro-arquivo>` (também usa só uma cópia).

## Sintomas de cookies expirados

- `Sign in to confirm your age` ou `Sign in to confirm you're not a bot`, mesmo com o arquivo presente;
- `age-restricted` / `Requested format is not available` só em vídeos que exigem login;
- o script avisa que o `cookies-master.txt` não existe.

Vídeos públicos normais devem baixar sem cookies. Se até eles falharem, vá para "Outros problemas".

## Como renovar o `cookies-master.txt`

1. Abra uma **janela anônima** do navegador e entre no YouTube com a conta que tem a idade verificada.
2. Abra o vídeo problemático e confirme que ele toca.
3. Ainda nessa aba, exporte os cookies de `youtube.com` com uma extensão como
   "Get cookies.txt LOCALLY" (formato Netscape).
4. **Feche a janela anônima sem abrir o YouTube de novo.** O YouTube rotaciona os cookies de abas abertas
   e isso invalida o arquivo exportado.
5. Salve o arquivo como `C:\cortes\cookies-master.txt`. Ele deve ter dezenas de linhas e
   incluir `SID` e `__Secure-3PSID`.
6. Faça uma cópia de segurança (por exemplo `cookies-master.bak.txt`) para poder restaurar.

Não use o `cookies.txt` antigo de `C:\cortes`: o yt-dlp o reescreveu várias vezes e ele ficou quase sem login.

## Outros problemas

- **Só aparecem miniaturas ou 360p:** atualize o yt-dlp e os componentes:
  `python -m pip install -U --pre "yt-dlp[default]" yt-dlp-ejs bgutil-ytdlp-pot-provider`.
- **Aviso de que o PO token script não foi encontrado:** refaça o build do gerador:
  `cd %USERPROFILE%\bgutil-ytdlp-pot-provider\server` e depois `npm ci` e `npx tsc`.
  A versão do repositório deve ser a mesma do plugin (`pip show bgutil-ytdlp-pot-provider`).
- **Erro no faster-whisper (`metadata_errors`):** o pacote `av` está novo demais. Use
  `python -m pip install "av>=14,<17"`.
- **Último recurso:** baixe o vídeo por outro meio e passe o MP4 direto para a transcrição.

## Segurança

- O `cookies-master.txt` dá acesso à sua conta do Google. Não compartilhe, não suba para nuvem
  e não o coloque em repositório.
- Para encerrar o acesso, saia da conta em todos os dispositivos ou troque a senha.
