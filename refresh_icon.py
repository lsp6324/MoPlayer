import ctypes  # 调用 Windows Shell 的图标更新通知。
import sys  # 读取需要刷新显示的可执行文件路径。
from pathlib import Path  # 使用完整路径定位已更新的 EXE。

def refresh(path):  # 只通知资源管理器重新读取图标，不删除缓存文件或重启桌面。
    target = Path(path).resolve(strict=True)  # 确认目标确实存在。
    shell = ctypes.windll.shell32  # 使用 Windows 自带的 Shell 接口。
    shell.SHChangeNotify.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]  # 保留完整的 64 位路径指针。
    shell.SHChangeNotify.restype = None  # Shell 通知接口没有成功返回值。
    name = ctypes.c_wchar_p(str(target))  # 将文件名转换成 Windows Unicode 字符串。
    shell.SHChangeNotify(0x00002000, 0x1005, ctypes.cast(name, ctypes.c_void_p), None)  # 发送 UPDATEITEM 与 PATHW 通知，等待 Shell 接收。
    shell.SHChangeNotify(0x08000000, 0x1000, None, None)  # 通知 Shell 使已缓存的图标关联失效并重新读取。
    print(f'已发送图标刷新通知：{target}')  # 如实说明已发送通知，不将通知当成可见效果验收。

if __name__ == '__main__':  # 允许构建脚本单独调用。
    refresh(sys.argv[1])  # 刷新调用者明确指定的交付文件。
