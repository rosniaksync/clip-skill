#!/usr/bin/env python3
"""Instala a limpeza automática para rodar toda vez que você entra no Windows (ligar o note).

Uso:
  install_cleanup.py            # instala (um atalho escondido na pasta Inicializar do Windows; não precisa de admin)
  install_cleanup.py --remove   # desinstala

A limpeza (scripts/cleanup.py) apaga o que não foi mexido nas últimas horas, então nunca pega um
trabalho em andamento. Fica só o histórico de onde parou.
"""
import argparse
import os
import platform
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "limpeza-cortes.vbs"


def startup_dir():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remove", action="store_true")
    a = ap.parse_args()
    script = os.path.join(HERE, "cleanup.py")

    if platform.system() != "Windows":
        print("Fora do Windows, agende você mesmo para rodar ao entrar no sistema, por exemplo (crontab -e):")
        print(f'  @reboot sleep 60 && "{sys.executable}" "{script}"')
        return

    path = os.path.join(startup_dir(), NAME)
    if a.remove:
        if os.path.exists(path):
            os.remove(path)
            print(f"✓ Limpeza automática removida ({path})")
        else:
            print("A limpeza automática não estava instalada.")
        return

    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    # espera 1 minuto depois do login (o Windows termina de abrir) e roda escondido
    vbs = ('Set sh = CreateObject("WScript.Shell")\r\n'
           'WScript.Sleep 60000\r\n'
           f'sh.Run """{exe}"" ""{script}""", 0, False\r\n')
    os.makedirs(startup_dir(), exist_ok=True)
    with open(path, "w", encoding="utf-16") as f:
        f.write(vbs)
    print(f"✓ Limpeza automática instalada: roda 1 minuto depois de você entrar no Windows.\n  ({path})")
    print("  Para ver o que ela faria agora sem apagar nada: python scripts/cleanup.py --dry-run")


if __name__ == "__main__":
    main()
