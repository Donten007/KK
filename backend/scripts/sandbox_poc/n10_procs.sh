#!/usr/bin/env bash
# N10 进程数超限（反向断言）：pids-limit=128，起 300 个后台进程必须被拒。
# 退出码语义：0 = 限额生效；1 = 限额失效。
set -u
count=0
for i in $(seq 1 300); do
  sleep 60 2>/dev/null &
  count=$((count + 1))
done
sleep 1
pids=$(jobs -p)
[ -n "$pids" ] && kill $pids 2>/dev/null
echo "spawned=$count"
if [ "$count" -ge 250 ]; then
  echo "LIMIT_BROKEN"
  exit 1
else
  echo "LIMIT_ENFORCED"
  exit 0
fi
