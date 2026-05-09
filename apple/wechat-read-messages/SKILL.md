---
name: wechat-read-messages
description: 用 lldb 从 WeChat Mac 进程内存提取 SQLCipher key，解密本地聊天记录数据库，精准查询指定联系人和日期的消息。Use lldb to extract SQLCipher key from WeChat Mac process memory, decrypt local chat DB, and query messages by contact and date.
triggers:
  - 读微信聊天记录
  - 查微信消息
  - wechat chat history
  - read wechat messages
---

# Hermes AI Agent 读取微信聊天记录
# Read WeChat Chat History via Hermes AI Agent

---

## ⚠️ 免责声明 / Disclaimer

**中文：** 本 skill 仅供用于读取**你自己设备上你自己账号**的微信聊天记录，用于个人数据备份、分析或 AI 辅助场景。严禁用于读取他人数据。使用者须自行承担全部法律责任。本方法涉及进程内存读取，可能违反微信用户协议，请自行评估风险。

**English:** This skill is intended solely for reading chat history from **your own WeChat account on your own device**, for personal backup, analysis, or AI-assisted use cases. Do NOT use this to access anyone else's data. You assume full legal responsibility for your use. This method involves reading process memory and may violate WeChat's Terms of Service — use at your own risk.

---

## 环境要求 / Prerequisites

- macOS，Apple Silicon（ARM64）
- WeChat Mac 版（测试版本：微信 3.x）
- Xcode Command Line Tools（提供 lldb）：`xcode-select --install`
- Python 3：`pip3 install sqlcipher3`（有 arm64 prebuilt wheel，直接装）

---

## 原理 / How It Works

WeChat Mac 用 **SQLCipher 3** 加密本地聊天数据库。启动时调用 `sqlite3_key(db, key, keyLen)`，key 以明文形式作为第二个参数（ARM64 x1 寄存器）传入。用 lldb 在该函数上打断点，直接从进程内存读出 key。

拿到 key 后，用 `sqlcipher3` Python 库以 `cipher_compatibility = 3` 参数解密数据库，直接 SQL 查询。

---

## Step 1：获取 SQLCipher Key

> **key 何时失效：** 微信重新登录账号、或大版本更新后可能变。变了重跑此步即可。

**必须完全退出微信，用 lldb launch 启动**，才能拦截到 `sqlite3_key` 的第一次调用。已运行的 WeChat attach 上去会错过时机。

```bash
# 完全退出微信
kill $(pgrep -x WeChat) 2>/dev/null
sleep 1
rm -f /tmp/wechat_key.txt
```

写 lldb Python hook（见 scripts/wechat_hook.py），然后：

```bash
# lldb 启动脚本
cat > /tmp/lldb_launch.txt << 'EOF'
target create /Applications/WeChat.app/Contents/MacOS/WeChat
command script import /tmp/wechat_hook.py
process launch
EOF

# 后台运行，等微信加载 DB（约 20 秒）
lldb --source /tmp/lldb_launch.txt > /tmp/lldb_out.txt 2>&1 &
sleep 25 && kill %1 2>/dev/null

# 读取 key（所有行都是同一个值，取第一行）
head -1 /tmp/wechat_key.txt
```

输出形如：`len=32 hex=<64位hex字符串>`，hex 后面的值就是 KEY_HEX。

**将 KEY_HEX 和你的 wxid 保存到安全的地方（如密码管理器），不要硬编码进脚本。**

---

## Step 2：找到数据库路径

WeChat 数据按账号存放，账号目录名是微信 ID 的 MD5。用以下脚本动态查找：

```python
import os, glob

wechat_base = os.path.expanduser(
    "~/Library/Containers/com.tencent.xinWeChat/Data/Library/"
    "Application Support/com.tencent.xinWeChat/2.0b4.0.9/"
)

# 找包含 Message 子目录的账号文件夹（即已登录过的账号）
def find_account_dirs():
    pattern = os.path.join(wechat_base, "*", "Message")
    return [os.path.dirname(p) for p in glob.glob(pattern)
            if os.path.isdir(p)]

account_dirs = find_account_dirs()
print(account_dirs)  # 通常只有一个
BASE = account_dirs[0]
MSG_DIR    = os.path.join(BASE, "Message")
SESSION_DB = os.path.join(BASE, "Session", "session_new.db")
```

---

## Step 3：解密并打开数据库

```python
import sqlcipher3

KEY_HEX = "你的key"  # 从密码管理器取，不要硬编码

def open_db(path):
    conn = sqlcipher3.connect(path)
    c = conn.cursor()
    c.execute(f"PRAGMA key = \"x'{KEY_HEX}'\";")
    c.execute("PRAGMA cipher_compatibility = 3;")  # 关键！其他参数组合无效
    return conn, c
```

---

## Step 4：查找联系人

联系人名字 → wxid 的映射在 `Session/session_new.db` 的 `SessionAbstract` 表，`_packed_MMSessionInfo` 字段是 protobuf，field tag `0x1a` 后跟 display name。

```python
def build_contact_map(session_db):
    conn, c = open_db(session_db)
    c.execute("SELECT m_nsUserName, _packed_MMSessionInfo FROM SessionAbstract")
    rows = c.fetchall()
    conn.close()
    result = {}
    for username, blob in rows:
        name = extract_display_name(blob)
        result[username] = name or username
    return result

def extract_display_name(blob):
    """从 protobuf blob 提取 display name（field tag 0x1a）"""
    if not blob:
        return None
    data = bytes(blob)
    for i in range(len(data) - 2):
        if data[i] == 0x1a:
            length = data[i+1]
            if 2 <= length <= 40 and i + 2 + length <= len(data):
                chunk = data[i+2:i+2+length]
                try:
                    s = chunk.decode('utf-8')
                    if s and not s.startswith('http') and '@' not in s:
                        return s
                except:
                    pass
    return None
```

---

## Step 5：查询消息

每个联系人对应一张表，表名 = `Chat_` + MD5(wxid)：

```python
import hashlib

def username_to_table(username):
    return "Chat_" + hashlib.md5(username.encode()).hexdigest()
```

消息分布在 `msg_0.db` ~ `msg_9.db`，遍历找对应表：

```python
import os

def find_db_for_user(username, msg_dir):
    table = username_to_table(username)
    for i in range(20):  # 通常不超过 10 个
        db_path = os.path.join(msg_dir, f"msg_{i}.db")
        if not os.path.exists(db_path):
            break
        conn, c = open_db(db_path)
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if c.fetchone():
            conn.close()
            return db_path, table
        conn.close()
    return None, None
```

消息表列名（注意不是通用的 CreateTime）：

| 列名 | 含义 |
|------|------|
| `msgCreateTime` | Unix 时间戳 |
| `mesDes` | 0=我发，1=对方发 |
| `messageType` | 1=文字 3=图片 34=语音 43=视频 47=表情 49=链接/文件 10000=系统消息 |
| `msgContent` | 消息内容（文字时为 UTF-8） |

按日期精准查询：

```python
from datetime import datetime, timedelta

def query_by_date(username, date_str, msg_dir):
    date = datetime.strptime(date_str, "%Y-%m-%d")
    start = int(date.timestamp())
    end   = int((date + timedelta(days=1)).timestamp())

    db_path, table = find_db_for_user(username, msg_dir)
    if not db_path:
        return []
    conn, c = open_db(db_path)
    c.execute(f"""
        SELECT msgCreateTime, mesDes, messageType, msgContent
        FROM {table}
        WHERE msgCreateTime BETWEEN ? AND ?
        ORDER BY msgCreateTime ASC
    """, (start, end))
    rows = c.fetchall()
    conn.close()
    return rows
```

---

## 坑记录 / Pitfalls

1. **必须 lldb launch，不能 attach 已运行进程。** DB 在启动时就打开了，attach 上去已经错过 sqlite3_key 的调用时机。

2. **lldb source 文件里不能内联 Python 代码块（`script ... end_script` 格式不稳定）。** 必须用 `command script import /path/to/hook.py` 导入外部 .py 文件。

3. **SQLCipher 参数只有 `cipher_compatibility = 3` 有效。** 手动设 page_size / kdf_iter / hmac_algorithm 的各种组合全部返回空表。

4. **联系人 DB（`wccontact_new2.db`）在 lldb launch 未登录状态下是空文件。** 联系人名字要从 `Session/session_new.db` 里取，不影响消息查询。

5. **消息列名是 `msgCreateTime`，不是 `CreateTime`。** 不同版本的 WeChat 可能有差异，建议先 `PRAGMA table_info(表名)` 确认列名。

---

## 完整示例脚本

见 `scripts/wechat_query.py`
