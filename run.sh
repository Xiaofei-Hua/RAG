#!/bin/bash
# RAG Platform 启动脚本

cd "$(dirname "$0")"

echo "启动 RAG Platform..."

# 1. 启动 Milvus (如果未运行)
if ! sudo docker ps | grep -q "milvus-standalone"; then
    if sudo docker ps -a | grep -q "milvus-standalone"; then
        sudo docker start milvus-standalone
    else
        sudo docker run -d --name milvus-standalone \
            -p 19530:19530 -p 9091:9091 \
            -v "$(pwd)/volumes/milvus:/var/lib/milvus" \
            milvusdb/milvus:v2.6.11 milvus run standalone
    fi
    echo "Milvus 启动中..."
else
    echo "Milvus 已运行"
fi

# 2. 启动后端
if ! lsof -i:8000 -t >/dev/null 2>&1; then
    nohup python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 > logs/backend.log 2>&1 &
    echo "后端启动: http://localhost:8000"
else
    echo "后端已运行"
fi

# 3. 启动前端
if ! lsof -i:5173 -t >/dev/null 2>&1; then
    cd web && nohup npm run dev > ../logs/frontend.log 2>&1 &
    cd ..
    echo "前端启动: http://localhost:5173"
else
    echo "前端已运行"
fi

echo ""
echo "服务地址:"
echo "  前端:  http://localhost:5173"
echo "  后端:  http://localhost:8000"
echo "  API:   http://localhost:8000/docs"