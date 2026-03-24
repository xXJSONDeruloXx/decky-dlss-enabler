set shell := ["bash", "-euo", "pipefail", "-c"]

zip_path := "out/DLSS Enabler.zip"
deck_host := "deck@192.168.0.241"
deck_dest := "~/Desktop/"

install:
    pnpm install

frontend:
    pnpm build

zip:
    bash .vscode/build.sh

scp:
    scp 'out/DLSS Enabler.zip' deck@192.168.0.241:~/Desktop/

ship:
    bash .vscode/build.sh
    scp -o StrictHostKeyChecking=accept-new {{zip_path}} {{deck_host}}:{{deck_dest}}
