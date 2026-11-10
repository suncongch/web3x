#!/usr/bin/env python3
"""
Web3X 项目 - 快速测试脚本

这个脚本可以用来：
1. 验证依赖是否正确安装
2. 测试数据库连接
3. 创建示例数据（可选）
4. 检查应用配置
"""

import os
import sys

def check_environment():
    """检查运行环境"""
    print("🔍 检查 Python 环境...")
    
    version = sys.version_info
    print(f"✅ Python 版本: {version.major}.{version.minor}.{version.micro}")
    
    if version.major < 3 or (version.major == 3 and version.minor < 7):
        print("❌ 需要 Python 3.7 或更高版本")
        return False
    
    return True

def check_dependencies():
    """检查依赖是否安装"""
    print("\n📦 检查依赖...")
    
    required = {
        'flask': 'Flask',
        'flask_sqlalchemy': 'Flask-SQLAlchemy',
        'werkzeug': 'Werkzeug',
    }
    
    all_installed = True
    for module, name in required.items():
        try:
            __import__(module)
            print(f"✅ {name} 已安装")
        except ImportError:
            print(f"❌ {name} 未安装")
            all_installed = False
    
    if not all_installed:
        print("\n📥 请运行: pip install -r requirements.txt")
        return False
    
    return True

def check_project_structure():
    """检查项目文件结构"""
    print("\n📁 检查项目结构...")
    
    base_path = os.path.dirname(os.path.abspath(__file__))
    
    required_files = [
        'app.py',
        'requirements.txt',
        'templates/base.html',
        'templates/login.html',
        'templates/register.html',
        'templates/dashboard.html',
        'templates/home.html',
        'templates/purchase.html',
        'templates/tutorial.html',
        'templates/support.html',
    ]
    
    all_exist = True
    for file in required_files:
        file_path = os.path.join(base_path, file)
        if os.path.exists(file_path):
            print(f"✅ {file}")
        else:
            print(f"❌ {file} 缺失")
            all_exist = False
    
    return all_exist

def check_app_config():
    """检查应用配置"""
    print("\n⚙️  检查应用配置...")
    
    try:
        from app import app, db
        
        print(f"✅ Flask 应用加载成功")
        print(f"✅ 数据库 URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
        print(f"✅ Debug 模式: {app.debug}")
        
        return True
    except Exception as e:
        print(f"❌ 应用加载失败: {e}")
        return False

def create_test_user():
    """创建测试用户"""
    print("\n👤 创建测试用户...")
    
    try:
        from app import app, db, User
        
        with app.app_context():
            # 检查测试用户是否存在
            test_user = User.query.filter_by(username='testuser').first()
            
            if test_user:
                print("✅ 测试用户已存在")
                print(f"   用户名: testuser")
                print(f"   邮箱: {test_user.email}")
                return True
            
            # 创建新用户
            user = User(
                username='testuser',
                email='test@example.com'
            )
            user.set_password('123456')
            
            db.session.add(user)
            db.session.commit()
            
            print("✅ 测试用户创建成功")
            print(f"   用户名: testuser")
            print(f"   密码: 123456")
            print(f"   邮箱: test@example.com")
            
            return True
    except Exception as e:
        print(f"❌ 创建用户失败: {e}")
        return False

def main():
    """主函数"""
    print("=" * 60)
    print("         Web3X 项目 - 环境检查工具")
    print("=" * 60)
    
    checks = [
        ("Python 环境检查", check_environment),
        ("依赖检查", check_dependencies),
        ("项目结构检查", check_project_structure),
        ("应用配置检查", check_app_config),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ {name} 出错: {e}")
            results.append((name, False))
    
    # 总结
    print("\n" + "=" * 60)
    print("                    检查总结")
    print("=" * 60)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {name}")
    
    all_pass = all(result for _, result in results)
    
    if all_pass:
        print("\n" + "=" * 60)
        print("✅ 所有检查通过！应用已准备就绪。")
        print("\n现在可以运行应用：")
        print("  python3 app.py")
        print("\n然后在浏览器打开：")
        print("  http://localhost:5000")
        print("=" * 60)
        
        # 询问是否创建测试用户
        response = input("\n是否创建测试用户? (y/n): ").lower()
        if response == 'y':
            create_test_user()
            print("\n登录时使用:")
            print("  用户名: testuser")
            print("  密码: 123456")
        
        return 0
    else:
        print("\n" + "=" * 60)
        print("❌ 存在未通过的检查项")
        print("请修复上述问题后再试。")
        print("=" * 60)
        return 1

if __name__ == '__main__':
    sys.exit(main())
