#!/bin/bash
# RAG Platform 停止脚本

cd "$(dirname "$0")"

echo "停止 RAG Platform..."

# 停止前端
if lsof -i:5173 -t >/dev/null 2>&1; then
    kill $(lsof -i:5173 -t) 2>/dev/null
    echo "前端已停止"
fi

# 停止后端
if lsof -i:8000 -t >/dev/null 2>&1; then
    kill $(lsof -i:8000 -t) 2>/dev/null
    echo "后端已停止"
fi

# 停止 Milvus
if sudo docker ps | grep -q "milvus-standalone"; then
    sudo docker stop milvus-standalone >/dev/null
    echo "Milvus 已停止"
fi

echo "所有服务已停止"