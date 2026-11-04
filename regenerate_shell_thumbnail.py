import ctypes  # 调用 Windows 官方缩略图缓存接口。
import json  # 输出实测结果而不导出视频画面。
import sys  # 接收用户明确指定的文件路径。
from pathlib import Path  # 验证视频文件确实存在。
from ctypes import wintypes  # 使用 Windows 标准整数与路径类型。

class GUID(ctypes.Structure):  # 保持 COM GUID 的正确二进制布局。
    _fields_ = [('a', wintypes.DWORD), ('b', wintypes.WORD), ('c', wintypes.WORD), ('d', ctypes.c_ubyte * 8)]  # 固定为十六字节。

def guid(text):  # 将标准 GUID 文本转换成 COM 参数。
    result = GUID()  # 创建正确对齐的缓冲区。
    ctypes.windll.ole32.CLSIDFromString(text, ctypes.byref(result))  # 由 Windows 解析 GUID。
    return result  # 避免手工计算字段字节序。

def release(pointer):  # 释放本次持有的 COM 对象。
    if pointer.value:  # 失败调用不一定返回对象。
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents  # 读取 IUnknown 虚函数表。
        ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(table[2])(pointer)  # 调用 IUnknown.Release。

def regenerate(path, extraction_flags=0x4):  # 默认隔离提取，诊断时可明确指定 Windows 支持的提取标志。
    path = Path(path).resolve(strict=True)  # 不按同名猜测其他视频。
    if not path.is_file():  # 缓存请求只能指向真实文件。
        raise ValueError('目标不是文件。')  # 避免递归操作目录。
    ole, shell = ctypes.windll.ole32, ctypes.windll.shell32  # 使用系统现有组件，无需新增插件。
    ole.CoInitialize(None)  # 当前线程初始化 COM。
    item, cache = ctypes.c_void_p(), ctypes.c_void_p()  # 分别持有 Shell 文件与缩略图缓存对象。
    report = {'file': str(path), 'sizes': []}  # 只保存接口结果，不保存用户视频帧。
    try:  # 所有对象均在 finally 中释放。
        shell.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]  # 正确传递中文路径。
        shell.SHCreateItemFromParsingName.restype = ctypes.c_long  # HRESULT 保持有符号三十二位。
        result = shell.SHCreateItemFromParsingName(str(path), None, ctypes.byref(guid('{43826D1E-E718-42EE-BC55-A1E261C37BFE}')), ctypes.byref(item))  # 获取 IShellItem。
        if result < 0:  # 文件不可读时不声称修复成功。
            raise OSError(hex(result & 0xffffffff))  # 保留真实错误码。
        ole.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]  # 正确处理六十四位 COM 指针。
        ole.CoCreateInstance.restype = ctypes.c_long  # 获取系统返回状态。
        result = ole.CoCreateInstance(ctypes.byref(guid('{50ef4544-ac9f-4a8e-b21b-8a26180db13f}')), None, 1, ctypes.byref(guid('{F676C15D-596A-4ce2-8234-33996F445DB1}')), ctypes.byref(cache))  # 获取本机 IThumbnailCache。
        if result < 0:  # 本机组件异常时明确报告。
            raise OSError(hex(result & 0xffffffff))  # 不改写或安装系统组件。
        table = ctypes.cast(cache, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents  # 查找缩略图缓存方法。
        get = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p)(table[3])  # 绑定 GetThumbnail。
        for size in [96, 256, 1024]:  # 覆盖资源管理器常见的中、大和超大图标缓存档位。
            bitmap, flags = ctypes.c_void_p(), wintypes.DWORD()  # 接收缓存位图对象与质量标记。
            try:  # 每种尺寸均独立记录结果。
                result = get(cache, item, size, extraction_flags, ctypes.byref(bitmap), ctypes.byref(flags), None)  # 默认 FORCEEXTRACTION 忽略旧缓存并重新提取和缓存。
                report['sizes'].append({'size': size, 'ok': result >= 0 and bool(bitmap.value), 'hresult': hex(result & 0xffffffff), 'flags': flags.value})  # 不把后备图标算作成功。
            finally:  # 缓存位图对象由 Shell 管理，不能直接 DeleteObject。
                release(bitmap)  # 释放 ISharedBitmap 引用。
        shell.SHChangeNotify.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]  # 使用 Unicode 路径通知签名。
        for event, target in [(0x2000, path), (0x1000, path.parent)]:  # 同时刷新文件本身与它所在文件夹。
            name = ctypes.c_wchar_p(str(target))  # 保持字符串在调用期间有效。
            shell.SHChangeNotify(event, 0x1005, ctypes.cast(name, ctypes.c_void_p), None)  # 发送 UPDATEITEM 或 UPDATEDIR，等待 Shell 接收。
        return report  # 报告缓存真实生成情况。
    finally:  # 错误路径同样释放系统资源。
        release(cache)  # 释放缩略图缓存对象。
        release(item)  # 释放文件对象。
        ole.CoUninitialize()  # 结束本次 COM 初始化。

if __name__ == '__main__':  # 支持逐个指定需要修复的文件。
    print(json.dumps([regenerate(path) for path in sys.argv[1:]], ensure_ascii=False, indent=2))  # 不扫描或修改其他视频。
