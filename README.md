# Web3X - 用户注册和登录网站

这是一个使用 Python/Flask 构建的完整网站，包含用户注册、登录和四个主要功能模块。

## 项目结构

```
web3x/
├── app.py                   # Flask 应用主文件
├── requirements.txt         # Python 依赖
├── users.db                 # SQLite 数据库（自动生成）
└── templates/               # HTML 模板文件夹
    ├── base.html           # 基础模板（包含侧边栏）
    ├── login.html          # 登录页面
    ├── register.html       # 注册页面
    ├── dashboard.html      # 仪表板页面
    ├── home.html           # 主页
    ├── purchase.html       # 购买页面
    ├── tutorial.html       # 教程页面
    └── support.html        # 客服页面
```

## 功能特性

### 1. 用户认证系统
- ✅ 用户注册（用户名、邮箱、密码）
- ✅ 用户登录
- ✅ 密码加密存储
- ✅ 会话管理
- ✅ 登出功能

### 2. 登录后的四个导航菜单
- 🏠 **主页** - 展示平台特性和统计信息
- 🛒 **购买** - 产品浏览和购物车功能
- 📚 **教程** - 分级学习课程（初级、中级、高级）
- 💬 **客服** - 客户支持、FAQ 和联系表单

### 3. UI/UX 特性
- 🎨 现代化设计，渐变色主题
- 📱 完全响应式（支持移动设备）
- ✨ 平滑的交互动画
- 🌙 深色侧边栏设计
- 🎯 直观的用户导航

## 安装和运行

### 前置要求
- Python 3.7+
- pip（Python 包管理器）

### 安装步骤

1. **克隆或下载项目**
```bash
cd /path/to/web3x
```

2. **安装依赖**
```bash
python3 -m pip install -r requirements.txt
```

3. **运行应用**
```bash
python3 app.py
```

4. **访问应用**
在浏览器中打开：
```
http://localhost:5000
```

## 使用流程

### 第一次使用

1. 访问 `http://localhost:5000`，自动重定向到登录页面
2. 点击"点击注册"链接进入注册页面
3. 填写用户名、邮箱、密码进行注册
4. 注册成功后重定向到登录页面
5. 用已注册的用户名和密码登录

### 登录后

登录成功后，您将进入仪表板，可以看到：
- 左侧侧边栏，包含四个导航菜单
- 统计信息卡片
- 最近活动列表
- 快速操作按钮

## 测试账户（示例）

注册一个新账户进行测试：
- 用户名：`testuser`
- 邮箱：`test@example.com`
- 密码：`123456`

## 技术栈

- **后端框架**：Flask 2.3.3
- **数据库**：SQLite（通过 Flask-SQLAlchemy）
- **密码加密**：Werkzeug
- **前端**：HTML5 + CSS3 + JavaScript（Vanilla）
- **模板引擎**：Jinja2

## 文件说明

### app.py
主应用文件，包含：
- Flask 应用初始化
- SQLAlchemy 数据库配置
- User 数据模型
- 所有路由和视图函数

### 核心路由

| 路由 | 方法 | 功能 |
|------|------|------|
| `/` | GET | 主页重定向 |
| `/register` | GET, POST | 用户注册 |
| `/login` | GET, POST | 用户登录 |
| `/dashboard` | GET | 仪表板 |
| `/home` | GET | 主页 |
| `/purchase` | GET | 购买页面 |
| `/tutorial` | GET | 教程页面 |
| `/support` | GET | 客服页面 |
| `/logout` | GET | 登出 |

## 安全说明

**注意**：此项目用于学习和演示目的。在生产环境中，需要考虑以下安全措施：

- 修改 `SECRET_KEY` 为安全的随机字符串
- 使用 HTTPS 而不是 HTTP
- 添加 CSRF 保护
- 实现速率限制防止暴力破解
- 定期安全审计
- 使用环境变量存储敏感信息

## 自定义和扩展

### 修改网站名称
编辑各文件中的 "Web3X" 为您的网站名称。

### 修改颜色主题
修改 CSS 中的渐变色：
```css
background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
```

### 添加更多产品
编辑 `templates/purchase.html`，在 `products-grid` 中添加新的产品卡片。

### 添加更多教程
编辑 `templates/tutorial.html`，在相应的类别部分添加新的教程卡片。

## 故障排除

### 无法启动应用
```bash
# 检查 Python 版本
python3 --version

# 检查 pip 是否正确安装
python3 -m pip --version

# 重新安装依赖
python3 -m pip install -r requirements.txt
```

### 数据库错误
```bash
# 删除旧的数据库文件
rm users.db

# 重新运行应用，会自动创建新数据库
python3 app.py
```

### 端口已占用
如果 5000 端口已被占用，编辑 `app.py` 最后一行：
```python
app.run(debug=True, port=8000)  # 改为其他端口
```

## 许可证

此项目仅供学习和个人使用。

## 联系方式

如有任何问题或建议，请通过项目中的客服页面提交反馈。

---

**祝您使用愉快！** 🚀
