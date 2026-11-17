# What makes a stream moment go viral as a short

Use these to rank candidates. A clip needs at least 2 of them to be worth making.

## How to find candidates (process)
1. Transcribe the whole block with the `tiny` model (fast; `small` refines only the candidates); read it ALL in 10-minute blocks
   (`read_blocks.py`), not only around audio/chat peaks. Funny stories and jokes are often said calmly.
2. While reading, look for: **jokes, twists/reversals, arguments/discussions, unexpected situations,
   funny stories with a payoff**, plus big reactions.
3. Extract frames of every candidate (`extract_frames.py`) and look at them: some of the best moments are
   visual with no speech (crash, chase, absurd scene, jump scare).
4. Re-transcribe only the candidates with `small`, then pick the final clips.
5. `find_hype.py` (audio/chat/"clipa") is a **support tool**: use it to cross-check candidates and to catch
   what reading missed. It never decides alone. A loud peak with nothing funny is dropped; a great
   story with no peak stays.

## Moment types that work (best first)
1. **Big emotional reaction** — screaming, uncontrollable laughter, rage, shock.
   Loud audio spike + streamer voice = gold.
2. **Clutch / insane play** — last-second escape, impossible kill, crazy stunt,
   perfect timing. Chat usually spams here.
3. **Fail / karma** — plan goes wrong, instant regret, "NOOO".
4. **Funny interaction** — roast, prank on another player, NPC/RP chaos,
   unexpected donation/TTS message.
5. **Story with a payoff** — setup → twist → punchline inside 45 seconds.
6. **Hot take / relatable line** — a quotable sentence people will comment on.

## Hook rules (first 2 seconds decide everything)
- Start at the peak or 1 second before it. Never start with a greeting,
  "okay so", silence, or loading screens.
- If the payoff is at the end, start on the most dramatic line and let the
  build-up play — or open with a 1–2s "flash-forward" isn't supported, so just
  trim the setup hard.
- The `hook` text must create curiosity, not describe: "HE DIDN'T SEE IT
  COMING 💀" beats "Funny moment in GTA".

## Length & ending
- From 20s up, no hard maximum (see `config.json`). Under 30s loops better; go past 59s
  when the story needs it, and never pad.
- End on the punchline or reaction. Cut 0.3–0.8s after the last word.
- A clean loop (end flows back into start) boosts rewatches.

## Skip
- Moments that need context from earlier in the stream.
- Long silences, menus, AFK, loading, ad breaks, "be right back".
- Copyrighted music playing loudly (gets muted/claimed).
- Anything with personal info on screen (addresses, phone numbers, DMs).

## Titles & hashtags
- Title = hook + emoji + 1 game tag. Keep under 70 chars.
- Hashtags: game (#gta5 #gtarp), format (#shorts #gaming), streamer name,
  1–2 trending broad tags. 5–8 total.
