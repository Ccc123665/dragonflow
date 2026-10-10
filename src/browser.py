"""浏览器管理层：每账号一个独立持久 Profile，共享单个内嵌视图。

隔离机制（矩阵防关联的关键）
  · 每个账号一个 QWebEngineProfile，独立 storage path（Cookie / localStorage / 缓存）
  · 强制持久化 Cookie，关闭程序后登录态保留
  · 同一账号在本平台各后台之间共享该 Profile → 一次登录，站内互通
  · 不同账号之间完全隔离 → 同设备多账号不串号
"""
import os
from typing import Callable, Dict, Optional

from PyQt6.QtCore import QTimer, QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import (
    QWebEngineDownloadRequest, QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QFileDialog

import config
import store

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# 上传控件被点击时，宿主拦截并直接返回这些文件（图片/视频半自动上传）
# 存的是「路径列表」而不是单个路径：小红书一篇图文要一次传 1~9 张。
_pending_upload: Dict[str, list] = {}

# 没有预置文件、必须弹系统文件对话框时的**起始目录**（按账号）。
# 自动取当前内容的配图目录 —— 用户就算要手动选图，一打开就在对的文件夹，
# 而不是落到「最近 / 此电脑」对着隐藏的 %APPDATA% 目录发呆。
_suggested_dir: Dict[str, str] = {}

# 当前内容的**主题/标题**（按账号）。选图器用它把「同题批次」排最前 ——
# output 下躺着多个选题的批次，只按时间挑会把别的题的图挂到本题上
# （真实踩坑：本题 8 张，上一题 26 张的批次更新，自动挂图挂错批）。
_suggested_topic: Dict[str, str] = {}


def set_suggested_dir(aid: str, d: str) -> None:
    if d and os.path.isdir(d):
        _suggested_dir[aid] = d
    else:
        _suggested_dir.pop(aid, None)


def suggested_dir(aid: str) -> str:
    return _suggested_dir.get(aid, "")


def set_suggested_topic(aid: str, topic: str) -> None:
    t = str(topic or "").strip()
    if t:
        _suggested_topic[aid] = t
    else:
        _suggested_topic.pop(aid, None)


def suggested_topic(aid: str) -> str:
    return _suggested_topic.get(aid, "")


# 填充**中途**选图器交回文件后的回调（界面层注册）。
# 场景：一键填充时内容没图，适配脚本点开了页面的上传控件，
# 选图器这时才弹出 —— 用户选完「用这批」，文件直接喂给页面开始上传，
# 但这一轮填充已经以「需人工」收场。回调让界面层回写内容并
# 自动补一次填充，用户不用再手动点一次「一键填充」。
_files_picked_hook: Optional[Callable] = None


def set_files_picked_hook(fn: Optional[Callable]) -> None:
    global _files_picked_hook
    _files_picked_hook = fn


# 页面导航完成（防抖后）的回调 fn(aid)（界面层注册）。
# 场景：用户在发布页里扫码登录，登录必然伴随页面跳转 —— 宿主借此
# 重探登录态并写回账号库，账号矩阵的灰点才能变绿。以前只靠
# 「打开发布页后 4~8 秒探测两轮」，登录发生在那之后就没有任何时机
# 更新，账号明明登录着却永远挂「未登录」（真机反馈）。
_login_hook: Optional[Callable] = None


def set_login_hook(fn: Optional[Callable]) -> None:
    global _login_hook
    _login_hook = fn


def _fire_login_hook(aid: str) -> None:
    try:
        if _login_hook:
            _login_hook(aid)
    except Exception:
        pass  # 界面层回调出错不能反过来打死浏览器层


def set_pending_upload(aid: str, paths) -> None:
    """预置这个账号下一次点上传控件时要塞进去的文件。

    必须在适配脚本点上传控件**之前**设好 —— 适配脚本点的是页面里的
    `input[type=file]`，Qt 会回调 chooseFiles，那里把这里的路径交回去，
    浏览器就当成用户自己选了文件。没预置才会弹系统对话框。
    """
    if isinstance(paths, str):
        paths = [paths]
    _pending_upload[aid] = [p for p in (paths or []) if p]


def clear_pending_upload(aid: str) -> None:
    _pending_upload.pop(aid, None)


def pending_upload(aid: str) -> list:
    return list(_pending_upload.get(aid, []))


def _cap_for_platform(aid: str, files: list) -> list:
    """按平台单篇图片上限截断（小红书 18 张）。

    选图器交回的文件不经过 upload_files，必须在喂给页面前截——
    26 张整批塞给小红书会被整批拒收（实测：页面停在空上传态，一张都没传）。
    """
    try:
        import platforms as PF
        acc = store.get_account(store.load_accounts(), aid)
        mx = PF.max_images(acc["platform"]) if acc else 0
        if mx:
            files = PF._cap_images(acc["platform"], list(files))
    except Exception:
        pass
    return files


class WebPage(QWebEnginePage):
    """重写弹窗与文件选择行为。

    · createWindow：把 target=_blank / window.open 转成同页跳转，避免点了没反应
    · chooseFiles：优先返回宿主预设的素材文件，实现「自动塞文件」的半自动上传
    """

    def __init__(self, profile: QWebEngineProfile, aid: str, parent=None):
        super().__init__(profile, parent)
        self.aid = aid

    def createWindow(self, _type):
        return self

    def chooseFiles(self, mode, old_files, accepted_mime_types):
        preset = _pending_upload.get(self.aid)
        if preset:
            return list(preset)
        # 没有预置文件 → 先试应用内选图器：左侧是最近产出的批次
        # （同题批次排最前，其余新→旧），右侧缩略图，点「用这批」直接交回
        # 文件 —— 用户不用再去 %APPDATA% 深处找文件夹。选图器开不起来
        # （没有任何批次）才退回系统对话框，起始目录定位到当前内容的配图目录。
        try:
            from PyQt6.QtWidgets import QApplication
            from widgets.media_picker import pick_media_files
            res = pick_media_files(QApplication.activeWindow(),
                                   _suggested_dir.get(self.aid, ""),
                                   topic=_suggested_topic.get(self.aid, ""))
            if res is not None:
                files = list(res[0])
                if files:
                    files = _cap_for_platform(self.aid, files)
                if files and _files_picked_hook:
                    try:
                        _files_picked_hook(self.aid, files)
                    except Exception:
                        pass
                return files
        except Exception:
            pass
        paths, _ = QFileDialog.getOpenFileNames(
            None, "选择要上传的文件", _suggested_dir.get(self.aid, ""),
            "媒体文件 (*.png *.jpg *.jpeg *.gif *.webp *.mp4 *.mov);;所有文件 (*.*)"
        )
        return paths or []


class BrowserManager:
    """按账号管理 Profile 与页面。"""

    def __init__(self):
        self._profiles: Dict[str, QWebEngineProfile] = {}
        self._pages: Dict[str, WebPage] = {}
        self._view: Optional[QWebEngineView] = None
        self._download_hook: Optional[Callable] = None
        # 每账号一个防抖定时器：登录跳转常连着好几 loadFinished，
        # 只在页面「静下来」1.2s 后才通知界面层重探登录态
        self._login_timers: Dict[str, QTimer] = {}

    # ---------------------------------------------------------- 视图
    def attach_view(self, view: QWebEngineView) -> None:
        """绑定唯一的共享视图（由界面层提供）。"""
        self._view = view

    def view(self) -> Optional[QWebEngineView]:
        return self._view

    # ---------------------------------------------------------- Profile
    def profile(self, aid: str) -> QWebEngineProfile:
        if aid in self._profiles:
            return self._profiles[aid]
        prof = QWebEngineProfile(f"df_{aid}", self._view)
        prof.setPersistentStoragePath(config.profile_path(aid))
        prof.setCachePath(config.profile_path(aid) + "/cache")
        prof.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        prof.setHttpUserAgent(UA)
        prof.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        prof.downloadRequested.connect(self._on_download)
        self._profiles[aid] = prof
        return prof

    def page(self, aid: str) -> WebPage:
        if aid in self._pages:
            return self._pages[aid]
        page = WebPage(self.profile(aid), aid, self._view)
        s = page.settings()
        for attr in (
            QWebEngineSettings.WebAttribute.LocalStorageEnabled,
            QWebEngineSettings.WebAttribute.JavascriptEnabled,
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,
            QWebEngineSettings.WebAttribute.PluginsEnabled,
            QWebEngineSettings.WebAttribute.FullScreenSupportEnabled,
            QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled,
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            QWebEngineSettings.WebAttribute.ShowScrollBars,
        ):
            s.setAttribute(attr, True)
        page.loadFinished.connect(
            lambda ok, a=aid: self._schedule_login_probe(a, ok))
        self._pages[aid] = page
        return page

    # ---------------------------------------------------------- 操作
    def has_page(self, aid: str) -> bool:
        """这个账号当前有没有活着的页面（clear_profile 后为 False）。"""
        return aid in self._pages

    def _schedule_login_probe(self, aid: str, ok: bool) -> None:
        """页面每次导航完成都防抖触发一次登录态重探。

        扫码登录 = 跳转页面 = loadFinished —— 这是宿主能「感知登录完成」
        最可靠的钩子。加载失败不发（重定向链里偶尔有失败项，别当信号）。
        """
        if not ok or aid not in self._pages:
            return
        t = self._login_timers.get(aid)
        if t is None:
            t = QTimer()
            t.setSingleShot(True)
            t.timeout.connect(lambda a=aid: _fire_login_hook(a))
            self._login_timers[aid] = t
        t.start(1200)

    def open(self, aid: str, url: str) -> None:
        if not self._view:
            return
        page = self.page(aid)
        self._view.setPage(page)
        if url:
            page.load(QUrl(url))
        self._current = aid

    def current_account(self) -> str:
        return getattr(self, "_current", "")

    def reload(self) -> None:
        if self._view:
            self._view.reload()

    def clear_profile(self, aid: str) -> bool:
        """清掉某账号的登录态与缓存（用于「退出登录」）。"""
        self._pages.pop(aid, None)
        t = self._login_timers.pop(aid, None)
        if t:
            t.stop()
        prof = self._profiles.pop(aid, None)
        if prof:
            try:
                prof.deleteLater()
            except Exception:
                pass
        return store.clear_profile(aid)

    # ---------------------------------------------------------- 下载
    def set_download_hook(self, fn: Callable) -> None:
        self._download_hook = fn

    def _on_download(self, dl: QWebEngineDownloadRequest) -> None:
        # QtWebEngine 的下载默认「不接管就取消」，必须显式 accept
        try:
            dl.accept()
        except Exception:
            pass
        if self._download_hook:
            self._download_hook(dl)


BROWSER = BrowserManager()
