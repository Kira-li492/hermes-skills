"""
wechat_hook.py - lldb Python hook，拦截 WeChat 的 sqlite3_key 调用，提取 SQLCipher key
用法：在 lldb 里 `command script import /path/to/wechat_hook.py`
      key 会写入 /tmp/wechat_key.txt
"""
import lldb

def on_sqlite3_key(frame, bp_loc, extra_args, internal_dict):
    proc = frame.GetThread().GetProcess()
    x1 = frame.FindRegister("x1").GetValueAsUnsigned(0)
    x2 = frame.FindRegister("x2").GetValueAsUnsigned(0)
    if x1 == 0:
        return False
    keylen = x2 if 0 < x2 <= 128 else 32
    err = lldb.SBError()
    raw = proc.ReadMemory(x1, keylen, err)
    if err.Success() and raw:
        with open("/tmp/wechat_key.txt", "a") as f:
            f.write(f"len={keylen} hex={raw.hex()}\n")
        print(f"[KEY CAPTURED] len={keylen} hex={raw.hex()}")
    return False

def __lldb_init_module(debugger, internal_dict):
    target = debugger.GetSelectedTarget()
    bp = target.BreakpointCreateByName("sqlite3_key")
    bp.SetScriptCallbackFunction("wechat_hook.on_sqlite3_key")
    print(f"[*] sqlite3_key breakpoint set, {bp.GetNumLocations()} location(s)")
