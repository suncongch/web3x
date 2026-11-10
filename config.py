# Web3X 应用配置文件

# Flask 应用配置
DEBUG = True
TESTING = False

# 数据库配置
SQLALCHEMY_DATABASE_URI = 'sqlite:///users.db'
SQLALCHEMY_TRACK_MODIFICATIONS = False

# 安全配置
# 警告：生产环境中请修改此密钥为安全的随机字符串！
SECRET_KEY = 'your-secret-key-change-this-in-production'

# 会话配置
PERMANENT_SESSION_LIFETIME = 86400  # 24 小时
SESSION_COOKIE_SECURE = False  # 生产环境改为 True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# 服务器配置
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000
