#!/bin/bash

# Web3X 应用启动脚本

echo "🚀 启动 Web3X 应用..."
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误：未找到 Python3"
    exit 1
fi

echo "✅ Python 版本：$(python3 --version)"

# 检查依赖
echo ""
echo "📦 检查依赖..."
if python3 -c "import flask, flask_sqlalchemy, dotenv, yaml" 2>/dev/null; then
    echo "✅ Flask 已安装"
else
    echo "📥 正在安装依赖..."
    python3 -m pip install -r requirements.txt
fi

# 启动应用
echo ""
echo "🌐 启动服务器..."
echo "📍 访问地址：http://localhost:5000"
echo "🛑 按 Ctrl+C 停止服务器"
echo ""

python3 app.py
