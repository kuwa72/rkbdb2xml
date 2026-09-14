#!/usr/bin/env bash
set -e

# 導入時に必要なラベルを冪等に作成する。既存ラベルは --force で上書き。
# name|color|description
labels=(
    "ready|0e8a16|Ready to be worked on"
)

for entry in "${labels[@]}"; do
    name="${entry%%|*}"
    rest="${entry#*|}"
    color="${rest%%|*}"
    desc="${rest#*|}"
    gh label create "$name" --color "$color" --description "$desc" --force
done

echo "Labels ready!"
