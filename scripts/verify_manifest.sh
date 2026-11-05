#!/bin/sh
# 校验仓库里的镜像文件是否齐全、大小是否和 MANIFEST.tsv 一致。
# 用法：在仓库根目录执行  sh scripts/verify_manifest.sh
cd "$(dirname "$0")/.." || exit 1
missing=0; wrong=0; total=0
while IFS="$(printf '\t')" read -r path size; do
  case "$path" in ''|\#*) continue ;; esac
  total=$((total+1))
  if [ ! -f "$path" ]; then echo "MISSING  $path"; missing=$((missing+1)); continue; fi
  actual=$(wc -c < "$path" | tr -d ' ')
  if [ "$actual" != "$size" ]; then echo "SIZE     $path  expected=$size actual=$actual"; wrong=$((wrong+1)); fi
done < MANIFEST.tsv
echo "checked=$total missing=$missing size_mismatch=$wrong"
[ "$missing" -eq 0 ] && [ "$wrong" -eq 0 ]
