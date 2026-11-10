# 部署和运行指南

## 系统要求

- Python 3.7+
- Flask 2.0+
- SQLAlchemy
- Werkzeug

## 快速部署

### 1. 安装依赖
```bash
cd /Users/andy/Library/CloudStorage/SynologyDrive-mac/python/web3x
pip install -r requirements.txt
```

### 2. 运行应用
```bash
python3 app.py
```

### 3. 访问应用
打开浏览器并访问：
```
http://localhost:8000
```

## 完整使用流程

### 步骤 1: 注册账户
1. 在登录页面点击"注册"链接
2. 填写以下信息：
   - 用户名：任意唯一用户名
   - 邮箱：有效的邮箱地址
   - 密码：至少 6 位密码
3. 点击"注册"按钮

### 步骤 2: 登录
1. 返回登录页面
2. 输入注册的用户名和密码
3. 点击"登录"按钮
4. 成功登录后，页面会跳转到仪表板

### 步骤 3: 浏览购买页面
1. 在左侧导航栏点击"购买"
2. 你会看到 6 种不同的产品卡片
3. 每个产品卡片包含：
   - 产品图标
   - 产品名称
   - 产品描述
   - 产品价格
   - "立即购买"按钮

### 步骤 4: 进行购买
1. 在任意产品卡片上点击"立即购买"按钮
2. 按钮会显示加载动画："处理中..." 以及旋转的加载器
3. 等待 2-3 秒
4. 购买成功后，页面会显示成功提示框，包括：
   - 成功图标 ✓
   - 产品名称
   - 产品价格
   - "关闭"按钮

### 步骤 5: 关闭提示框
- 点击"关闭"按钮
- 或点击提示框外的区域
- 或等待自动关闭

## 数据库

### 自动初始化
应用启动时会自动：
1. 检查数据库是否存在
2. 如果不存在，创建数据库文件（users.db）
3. 创建 User 和 Order 表
4. 建立外键关系

### 数据库位置
```
/Users/andy/Library/CloudStorage/SynologyDrive-mac/python/web3x/users.db
```

### 查看数据库内容

#### 查看所有用户
```python
python3
>>> from app import app, User
>>> with app.app_context():
...     users = User.query.all()
...     for user in users:
...         print(f"用户: {user.username} ({user.email})")
```

#### 查看所有订单
```python
python3
>>> from app import app, Order, User
>>> with app.app_context():
...     orders = Order.query.all()
...     for order in orders:
...         user = User.query.get(order.user_id)
...         print(f"订单 {order.id}: {user.username} 购买了 {order.product_name} (¥{order.price})")
```

#### 查看特定用户的订单
```python
python3
>>> from app import app, User, Order
>>> with app.app_context():
...     user = User.query.filter_by(username='testuser').first()
...     if user:
...         orders = Order.query.filter_by(user_id=user.id).all()
...         for order in orders:
...             print(f"订单 {order.id}: {order.product_name}")
```

## 端口配置

### 当前配置
```python
# app.py
if __name__ == '__main__':
    app.run(debug=True, port=8000)
```

### 更改端口
如需使用其他端口，编辑 `app.py` 的最后两行：
```python
if __name__ == '__main__':
    app.run(debug=True, port=YOUR_PORT_NUMBER)
```

## 环境变量配置

### 修改 SECRET_KEY
编辑 `app.py` 中的第 9 行：
```python
app.config['SECRET_KEY'] = 'your-secure-secret-key-here'
```

### 修改数据库路径
编辑 `app.py` 中的第 10 行：
```python
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///your_db_path/users.db'
```

## 调试模式

### 启用调试模式
```python
# app.py - 已启用
app.run(debug=True, port=8000)
```

调试模式的优点：
- 代码更改时自动重新加载
- 更详细的错误信息
- 交互式调试器

### 禁用调试模式（生产环境）
```python
app.run(debug=False, port=8000)
```

## 日志和监控

### 查看应用日志
应用运行时，所有操作都会输出到终端：
```
* Serving Flask app 'app'
* Debug mode: on
* Running on http://127.0.0.1:8000
* Debugger is active!
```

### 查看数据库操作
启用 SQLAlchemy 日志记录（可选）：
```python
import logging
logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
```

## 生产部署

### 使用 Gunicorn（推荐）
```bash
# 安装 Gunicorn
pip install gunicorn

# 运行应用
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

### 使用 Nginx 反向代理（可选）
```nginx
server {
    listen 80;
    server_name your_domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 故障排除

### 问题 1: 模块导入错误
**错误信息**: ModuleNotFoundError: No module named 'flask'
**解决方案**:
```bash
pip install -r requirements.txt
```

### 问题 2: 端口被占用
**错误信息**: Address already in use
**解决方案**:
- 方法 1：改用其他端口（如 8001）
- 方法 2：关闭占用该端口的程序

### 问题 3: 数据库锁定
**错误信息**: database is locked
**解决方案**:
1. 关闭所有 Flask 实例
2. 删除 `users.db-shm` 和 `users.db-wal` 文件（如果存在）
3. 重新启动应用

### 问题 4: 购买返回 401
**症状**: 购买时显示"请先登录"错误
**解决方案**:
1. 确保已成功登录
2. 检查浏览器是否启用 Cookie
3. 清除浏览器缓存并重试

## 安全提示

1. **修改 SECRET_KEY**: 生产环境中一定要修改 `app.config['SECRET_KEY']`
2. **启用 HTTPS**: 生产环境应该使用 HTTPS 而不是 HTTP
3. **设置强密码**: 建议用户在注册时设置强密码
4. **定期备份**: 定期备份 `users.db` 数据库文件

## 参考文档

- [STATUS.md](./STATUS.md) - 系统运行状态
- [PURCHASE_FEATURE.md](./PURCHASE_FEATURE.md) - 购买功能详情
- [README.md](./README.md) - 项目概览
- [CHANGES.md](./CHANGES.md) - 最近的代码变更

## 技术支持

如遇到问题，请检查以下内容：
1. Python 版本是否为 3.7 或更高版本
2. 所有依赖是否已安装
3. 是否有足够的文件系统权限
4. 端口是否被其他程序占用
5. 数据库文件是否可访问

---

**最后更新**: 2024 年
**文档版本**: 1.0
