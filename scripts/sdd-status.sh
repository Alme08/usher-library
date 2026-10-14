#!/usr/bin/env bash
d="docs/specs/$1"
[ -d "$d" ] || { echo "No existe $d"; exit 1; }
for f in spec plan tasks; do
  [ -f "$d/$f.md" ] && echo "$f.md: sí" || echo "$f.md: no"
done
grep -m1 '^Estado:' "$d/spec.md"
if [ -f "$d/tasks.md" ]; then
  echo "Tareas: $(grep -c '^- \[x\]' "$d/tasks.md") verificadas, $(grep -c '^- \[~\]' "$d/tasks.md") solo estáticas, $(grep -c '^- \[ \]' "$d/tasks.md") pendientes"
fi