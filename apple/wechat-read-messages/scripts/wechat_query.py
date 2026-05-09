#!/usr/bin/env python3
"""
wechat_query.py - 查询微信聊天记录
用法：
    python3 wechat_query.py                        # 列出所有联系人
    python3 wechat_query.py "Nathan"               # 查找联系人
    python3 wechat_query.py "Nathan" 2026-05-01    # 查询某天消息
    python3 wechat_query.py "Nathan" all           # 查询全部消息

KEY_HEX 从你的密码管理器取，不要硬编码。
"""
import sqlcipher3
import sys
import os
import glob
import hashlib
from datetime import datetime, timedelta

# ---- 配置（从密码管理器取，不要硬编码） ----
KEY_HEX = os.environ.get("WECHAT_KEY", "")  # 也可以通过环境变量传入
if not KEY_HEX:
    print("请设置 WECHAT_KEY 环境变量，或在此处填入 key")
    sys.exit(1)

# ---- 动态查找账号目录 ----
def find_base_dir():
    wechat_root = os.path.expanduser(
        "~/Library/Containers/com.tencent.xinWeChat/Data/Library/"
        "Application Support/com.tencent.xinWeChat/2.0b4.0.9/"
    )
    matches = [os.path.dirname(p) for p in glob.glob(os.path.join(wechat_root, "*", "Message"))
               if os.path.isdir(p)]
    if not matches:
        print("找不到微信数据目录，请确认微信已登录过")
        sys.exit(1)
    return matches[0]

BASE       = find_base_dir()
MSG_DIR    = os.path.join(BASE, "Message")
SESSION_DB = os.path.join(BASE, "Session", "session_new.db")

# ---- DB 操作 ----
def open_db(path):
    conn = sqlcipher3.connect(path)
    c = conn.cursor()
    c.execute(f"PRAGMA key = \"x'{KEY_HEX}'\";")
    c.execute("PRAGMA cipher_compatibility = 3;")
    return conn, c

def username_to_table(username):
    return "Chat_" + hashlib.md5(username.encode()).hexdigest()

def find_db_for_user(username):
    table = username_to_table(username)
    for i in range(20):
        db_path = os.path.join(MSG_DIR, f"msg_{i}.db")
        if not os.path.exists(db_path):
            break
        try:
            conn, c = open_db(db_path)
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if c.fetchone():
                conn.close()
                return db_path, table
            conn.close()
        except:
            pass
    return None, None

# ---- 联系人名字提取 ----
def extract_display_name(blob):
    """从 _packed_MMSessionInfo protobuf 提取 display name（field tag 0x1a）"""
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

def build_contact_map():
    conn, c = open_db(SESSION_DB)
    c.execute("SELECT m_nsUserName, _packed_MMSessionInfo FROM SessionAbstract")
    rows = c.fetchall()
    conn.close()
    return {u: (extract_display_name(b) or u) for u, b in rows}

def search_contact(query, contact_map):
    q = query.lower()
    return [(u, n) for u, n in contact_map.items()
            if q in n.lower() or q in u.lower()]

# ---- 消息查询 ----
TYPE_MAP = {
    1: None, 3: "[图片]", 34: "[语音]", 43: "[视频]",
    47: "[表情]", 49: "[链接/文件]", 10000: "[系统消息]"
}

def format_message(ts, des, msg_type, content, sender_name):
    time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    sender   = "我" if des == 0 else sender_name
    if isinstance(content, bytes):
        content = content.decode('utf-8', errors='replace')
    label = TYPE_MAP.get(msg_type, f"[type={msg_type}]")
    body  = content if msg_type == 1 else label
    return f"[{time_str}] {sender}: {body}"

def query_messages(username, start_ts, end_ts, limit=1000):
    db_path, table = find_db_for_user(username)
    if not db_path:
        print(f"找不到消息表：{username}")
        return []
    conn, c = open_db(db_path)
    c.execute(f"""
        SELECT msgCreateTime, mesDes, messageType, msgContent
        FROM {table}
        WHERE msgCreateTime BETWEEN ? AND ?
        ORDER BY msgCreateTime ASC
        LIMIT ?
    """, (start_ts, end_ts, limit))
    rows = c.fetchall()
    conn.close()
    return rows

# ---- 主程序 ----
if __name__ == "__main__":
    contact_map = build_contact_map()

    if len(sys.argv) < 2:
        print(f"共 {len(contact_map)} 个会话：")
        for u, n in sorted(contact_map.items(), key=lambda x: x[1]):
            print(f"  {n:30s}  {u}")
        sys.exit(0)

    matches = search_contact(sys.argv[1], contact_map)
    if not matches:
        print(f"找不到联系人：{sys.argv[1]}")
        sys.exit(1)
    if len(matches) > 1:
        print("多个匹配：")
        for u, n in matches:
            print(f"  {n} ({u})")
        sys.exit(0)

    username, display_name = matches[0]
    print(f"联系人：{display_name} ({username})")

    if len(sys.argv) < 3:
        sys.exit(0)

    date_arg = sys.argv[2]
    if date_arg == "all":
        start_ts, end_ts = 0, int(datetime.now().timestamp()) + 86400
    else:
        d = datetime.strptime(date_arg, "%Y-%m-%d")
        start_ts = int(d.timestamp())
        end_ts   = int((d + timedelta(days=1)).timestamp())

    rows = query_messages(username, start_ts, end_ts)
    print(f"\n共 {len(rows)} 条消息\n" + "="*60)
    for r in rows:
        print(format_message(*r, display_name))
