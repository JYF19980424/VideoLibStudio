# -*- coding: utf-8 -*-
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
import webview
from core.api import Api


def _setup_logging():
    """写运行日志到程序目录 videolib.log（滚动，最多 2MB x 3 个），便于排错"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "videolib.log")
    try:
        fh = RotatingFileHandler(path, maxBytes=2 * 1024 * 1024,
                                 backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(fh)
    except Exception:
        pass


def on_closing():
    """窗口关闭时 flush WAL + 关数据库，防止丢数据"""
    try:
        from core import database as _db
        _db.close_all()
    except Exception:
        pass


def _cleanup_old_backup():
    """自动更新后清理旧版备份（VideoLibStudio.exe.bak）。"""
    try:
        from core import config as _cfg
        bak = os.path.join(_cfg.APP_DIR, "VideoLibStudio.exe.bak")
        if os.path.isfile(bak):
            os.remove(bak)
            logging.getLogger("videolib").info("已清理旧版备份: %s", bak)
    except Exception:
        pass


def _cleanup_runtime_residue():
    """清理 PyInstaller onefile 运行时解压残留（D:\\360MoveData\\VideoLibStudio_Runtime）。

    方案A（2026-10-13）：不再设 24 小时门槛——每次启动把历史 _MEI 残留全部删除，
    只跳过当前实例正在用的目录（sys._MEIPASS）。原因：频繁测试/强杀（异常退出）
    每次都会残留一个约 437MB 的 _MEI，24 小时门槛导致当天残留清不掉、磁盘越攒越满。
    """
    try:
        import shutil
        rt = "D:\\360MoveData\\VideoLibStudio_Runtime"
        if not os.path.isdir(rt):
            return
        cur = ""
        try:
            if getattr(sys, "_MEIPASS", ""):
                cur = os.path.normpath(sys._MEIPASS)
        except Exception:
            cur = ""
        for name in os.listdir(rt):
            p = os.path.join(rt, name)
            if not name.startswith("_MEI"):
                continue
            if cur and os.path.normpath(p) == cur:
                continue  # 当前实例正在用的目录不能删
            shutil.rmtree(p, ignore_errors=True)
            logging.getLogger("videolib").info("已清理运行时残留: %s", p)
    except Exception:
        pass


def _ensure_ui_dir():
    """打包版启动时把包内 ui 同步到 exe 所在目录（以包内为准，保证界面最新）。

    ⚠️ 以前只比较「文件大小」：新旧 app.js 恰好同大小时磁盘旧文件永远不被替换，
    客户界面停留在旧版（表现为"改了没生效/修了又坏"）。现改为逐文件 sha256 校验，
    内容不一致就覆盖，彻底杜绝同大小不同内容的漏更。
    """
    if not getattr(sys, "frozen", False):
        return
    import hashlib
    import shutil
    src = os.path.join(sys._MEIPASS, "ui")
    dst = os.path.join(os.path.dirname(sys.executable), "ui")
    try:
        if not os.path.isdir(src):
            return
        if not os.path.isdir(dst):
            shutil.copytree(src, dst)
            return
        for name in ("index.html", "app.js", "style.css"):
            sp = os.path.join(src, name)
            dp = os.path.join(dst, name)
            if not os.path.isfile(sp):
                continue
            with open(sp, "rb") as f:
                src_hash = hashlib.sha256(f.read()).hexdigest()
            same = False
            if os.path.isfile(dp):
                with open(dp, "rb") as f:
                    same = hashlib.sha256(f.read()).hexdigest() == src_hash
            if not same:
                shutil.copy2(sp, dp)
                logging.getLogger("videolib").info("已同步界面资源: %s", name)
        # 在线影视线路配置（白标线路一/线路二）：以包内为准同步，作者改配置后重新打包发版即生效
        for name in ("online_sites.json",):
            sp = os.path.join(src, name)
            dp = os.path.join(dst, name)
            if not os.path.isfile(sp):
                continue
            with open(sp, "rb") as f:
                src_hash = hashlib.sha256(f.read()).hexdigest()
            same = False
            if os.path.isfile(dp):
                with open(dp, "rb") as f:
                    same = hashlib.sha256(f.read()).hexdigest() == src_hash
            if not same:
                shutil.copy2(sp, dp)
                logging.getLogger("videolib").info("已同步在线影视线路配置: %s", name)
    except Exception:
        pass


def _hide_after_start(w):
    """启动完成后隐藏指定窗口（用于迅雷网页版登录窗口）"""
    def _hide():
        try:
            w.hide()
        except Exception:
            pass
    return _hide


def main():
    _setup_logging()
    _cleanup_old_backup()
    # 开源版已移除：_cleanup_runtime_residue()  # 硬编码路径清理，仅打包版需要
    _ensure_ui_dir()
    # 方案①：恢复固定用户数据目录里的历史网盘刮削记录（更新/换目录后资料库网盘封面墙不丢）
    # 开源版已移除：网盘刮削记录恢复（高级版功能）
    # try:
    #     from core import netdisk as _nd
    #     _nd.meta_restore_all()
    # except Exception:
    #     pass
    # 曾出现 WebView2 命中旧缓存导致"源码改了、界面还是旧的"。本地资源毫秒级可重取，
    # 压缓存零感知；内存缓存随会话结束失效，重启必加载磁盘最新界面。
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--disk-cache-size=1024")
    api = Api()
    # 界面加载：相对路径 "ui/index.html"，由 pywebview 内置 HTTP 服务器
    # 以工作目录为根加载（每次启动读磁盘最新 ui 文件）。
    # 说明：file:// 绝对路径在 WebView2 对中文路径报 ERR_FILE_NOT_FOUND；
    # 传 http://127.0.0.1:PORT 绝对 URL 又会被 pywebview _resolve_url 重新
    # 映射（Windows 下把 URL 当路径 relpath）而失败。相对路径 + is_app 分支
    # 直接使用窗口自带服务器，是历史版本验证过能正常显示的方式。
    # 主窗口固定 http_port=18080，避免随机端口被本机其它服务占用导致
    # 偶发"页面加载失败、窗口不显示"。
    if getattr(sys, "frozen", False):
        _base_dir = os.path.dirname(sys.executable)
        try:
            os.chdir(_base_dir)
        except Exception:
            pass
    else:
        # 源码模式：不 chdir，保持启动目录（=项目目录），pywebview
        # 服务器以当前工作目录为根，相对路径 "ui/index.html" 才能命中。
        _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 关键：网页里的新窗口链接（target=_blank / window.open，典型如在线影视的
    # 播放按钮）一律在本窗口内打开，绝不跳到系统浏览器 → 保证软件内在线观看。
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
    window = webview.create_window(
        "VideoLibStudio 视频库管家",
        "ui/index.html",
        js_api=api,
        width=1280,
        height=800,
        resizable=True,
        http_port=18080
    )
    api._window = window
    # 在线影视（直连白标模式）：主窗口导航到线路源站后，由 loaded 事件自动注入白标脚本
    # （隐藏站名/导航/广告、保留影片与搜索、右下角悬浮返回条）。返回主界面时 URL 不
    # 命中源站则不注入。每次源站页面（含翻页/搜索/播放页）加载完成都会重新注入。
    from core import config as _cfg

    def _on_online_loaded():
        try:
            api._stop_float_poll()
        except Exception:
            pass
        try:
            real = window.real_url or ""
            for _s in (_cfg.load_online_sites() or []):
                if real.startswith(_s.get("url", "")):
                    window.evaluate_js(api.get_whitelabel_js())
                    break
        except Exception:
            pass


    def _on_online_nav_start():
        # 每次导航开始：立即启动精简工具条高频注入轮询——新页面 DOM 一可用，
        # 「←返回 / 刷新 / 线路」工具条就出现，不用等整页（图片/广告）加载完成。
        try:
            api._start_float_poll()
        except Exception:
            pass

    window.events.before_load += _on_online_nav_start
    window.events.loaded += _on_online_loaded
    # 迅雷网页版登录窗口：预创建、启动后隐藏；点「网页版登录」时显示并加载
    # pan.xunlei.com，用户完成登录后由 api 读取页面 localStorage 保存凭据。
    # 开源版已移除：xlwin = webview.create_window(
    # 开源版已移除："迅雷云盘网页登录",
    # 开源版已移除："about:blank",
    # 开源版已移除：js_api=api,
    # 开源版已移除：width=980,
    # 开源版已移除：height=720,
    # 开源版已移除：resizable=True
    # 开源版已移除：)
    # 开源版已移除：api._xlwin = xlwin
    # 在线影视（高级资源库）：不再单独开窗口，改为主界面本页内嵌白标代理。
    # 软件启动时拉起本地白标代理（core.online_proxy，端口 18082），前端在线影视
    # 页面用 iframe 加载 http://127.0.0.1:18082/l1|/l2，代理转发线路站点并注入
    # 隐藏规则（导航/站名/域名/页脚全隐藏，只留影片内容与播放画面），客户在本页
    # 内浏览，全程接触不到原站界面与网址。
    # 开源版已移除：try:
    # 开源版已移除：from core import online_proxy
    # 开源版已移除：online_proxy.start_proxy()
    # 开源版已移除：except Exception:
    # 开源版已移除：pass
    # 开源版已移除：api._online_index = 0

    def _hide_precreated():
        """启动完成后隐藏所有预创建窗口（迅雷登录窗）"""
        # 开源版已移除：_hide_after_start(xlwin)()  # 迅雷登录窗口

    window.events.closing += on_closing
    # http_server=True：全局 HTTP 服务器，主窗口 18080 加载相对路径界面。
    webview.start(debug=False, func=_hide_precreated, http_server=True)


if __name__ == "__main__":
    main()
