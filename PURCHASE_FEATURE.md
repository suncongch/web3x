# 购买功能文档

## 功能描述

购买页面已完成，包含以下功能：

1. **产品展示**：6种不同的产品卡片，每个产品都有"立即购买"按钮
2. **购买流程**：
   - 用户点击"立即购买"按钮
   - 按钮显示加载动画（禁用状态 + 加载旋转器）
   - 前端发送购买请求到后端 API
   - 后端创建订单记录并存储到数据库
   - 返回成功响应，前端显示成功提示框

3. **安全保护**：
   - API 端点需要用户登录（session 验证）
   - 未登录用户请求返回 401 错误

## API 端点

### POST /api/purchase

**请求格式：**
```json
{
  "product_name": "产品名称",
  "price": 99.99
}
```

**成功响应（HTTP 200）：**
```json
{
  "success": true,
  "message": "购买成功",
  "order_id": 1
}
```

**失败响应 - 未登录（HTTP 401）：**
```json
{
  "success": false,
  "message": "请先登录"
}
```

**失败响应 - 其他错误（HTTP 400/500）：**
```json
{
  "success": false,
  "message": "错误信息"
}
```

## 前端实现

### JavaScript 函数

1. **purchaseProduct(productName, price, button)**
   - 处理购买按钮点击事件
   - 显示加载动画
   - 调用 API 端点
   - 处理响应

2. **showSuccessModal(productName, price)**
   - 显示成功提示框
   - 显示产品名称和价格

3. **closeSuccessModal()**
   - 关闭成功提示框

### CSS 样式

- **加载动画**：旋转的圆形加载器
- **模态框**：半透明背景 + 中央白色卡片
- **成功动画**：成功图标的缩放进入动画
- **响应式设计**：支持各种屏幕尺寸

## 数据库

### Order 表结构

```
id: 主键 (Integer)
user_id: 用户 ID (Integer, 外键关联 user)
product_name: 产品名称 (String)
price: 产品价格 (Float)
status: 订单状态 (String, 默认值: 'completed')
created_at: 创建时间 (DateTime, 默认为当前时间)
```

## 测试方式

### 1. 使用浏览器测试

1. 打开 http://localhost:5000
2. 注册新账户或使用现有账户登录
3. 导航到"购买"菜单
4. 点击任意产品的"立即购买"按钮
5. 观察：
   - 按钮显示加载动画
   - 2-3 秒后显示成功提示框
   - 提示框显示产品名称和价格

### 2. 使用 API 测试

```bash
# 测试 API（需要先登录获取 session）
curl -X POST http://localhost:5000/api/purchase \
  -H "Content-Type: application/json" \
  -d '{"product_name": "测试产品", "price": 99.99}' \
  -b "cookies.txt"
```

### 3. 检查数据库

```python
from app import app, Order
with app.app_context():
    orders = Order.query.all()
    for order in orders:
        print(f"订单 ID: {order.id}, 产品: {order.product_name}, 价格: {order.price}")
```

## 当前状态

✅ **已完成**：
- 产品卡片设计和展示
- "立即购买"按钮实现
- 前端 JavaScript 函数
- 加载动画和成功提示框
- 后端 API 端点
- 数据库 Order 表
- 会话验证和安全保护
- 测试验证

## 后续扩展

1. **支付集成**：
   - 连接真实支付网关（支付宝、微信支付等）
   - 修改 Order.status 字段：待支付 → 已支付 → 已发货 → 已完成

2. **订单管理**：
   - 添加用户的订单历史页面
   - 显示订单状态、时间等详细信息
   - 订单查询和搜索功能

3. **错误处理**：
   - 更详细的错误信息
   - 重试机制
   - 交易日志

4. **通知系统**：
   - 订单确认邮件
   - 支付成功通知
   - 发货通知

## 疑难排除

### 问题：购买按钮无响应
**解决**：检查浏览器控制台（F12）是否有 JavaScript 错误

### 问题：API 返回 401
**解决**：确保已登录，检查 session 中是否有 user_id

### 问题：订单没有保存到数据库
**解决**：检查数据库连接，确认 Order 表存在
