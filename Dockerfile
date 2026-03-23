FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置 Python 环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源代码
COPY . .

# 创建数据目录（会被 volume 覆盖）和 SQL 目录
RUN mkdir -p /app/工作总结 /app/output /app/sql

# 暴露端口
EXPOSE 5000

# 启动命令 - gunicorn 生产级 WSGI 服务器
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--timeout", "300", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
