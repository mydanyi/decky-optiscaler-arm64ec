// Simplified Chinese wording for the plugin's fixed UI text.
//
// Partial by type on purpose: an entry that is missing here falls back to the
// matching English entry in src/locales/en.ts, so this catalogue may lag behind
// English without ever showing a raw identifier to the user.
//
// Placeholders, proper names, file names and technical values are copied from
// the English entry unchanged, and the Chinese wording itself is the shipped
// translation.

import type { TranslationKey } from "./en";

const zhCN: Partial<Record<TranslationKey, string>> = {
  // Build section.
  "build.title": "OptiScaler 构建",
  "build.version": "版本",
  "build.notDownloaded": "尚未下载",
  "build.status.updateAvailable": "{version}，有可用更新（{remoteVersion}）",
  "build.status.upToDateSuffix": "，已是最新版本",
  "build.status.updateAvailableSuffix": "，有可用更新",
  "build.check": "检查更新",
  "build.downloadUpdate": "下载更新",
  "build.download": "下载 OptiScaler",
  "build.recopy.description": "将此构建重新复制到你已配置的 {count} 个游戏中。",
  "build.recopy.action": "更新已安装到游戏中的构建",

  // Per-game setup.
  "game.title": "按游戏配置",
  "game.error.title": "出错了",
  "game.none.title": "未找到游戏",
  "game.none.description": "未检测到已安装的 Steam 游戏。",
  "game.label": "游戏",
  "game.choose": "选择一个游戏",
  "game.status.label": "状态",
  "game.status.installed": "已安装为 {dll}（构建 {version}）",
  "game.status.notInstalled": "未安装",
  "game.dll.label": "加载用 DLL",
  "game.dll.description":
    "OptiScaler 安装时使用的文件名。如果该名称已被其他 MOD 占用，可在此更改。",
  "game.spoof.label": "伪装为 NVIDIA 显卡",
  "game.spoof.description": "向游戏报告为 NVIDIA 显卡，让游戏提供 DLSS 选项，再由 OptiScaler 接管。",
  "game.optipatcher.label": "加载 OptiPatcher",
  "game.optipatcher.description":
    "作为 OptiScaler 插件加载 OptiPatcher，用于修补那些用自身检查限制 DLSS 的游戏，让 OptiScaler 能够接管。",
  "game.targets.title": "安装位置",
  "game.targets.root": "游戏根目录",
  "game.targets.previous": "先前的安装目录",
  "game.install.needsBuild": "请先下载 OptiScaler 构建。",
  "game.install.description": "复制 DLL 和配置，并为你设置启动参数。",
  "game.install.reinstall": "重新安装",
  "game.install.action": "安装到此游戏",
  "game.uninstall.description": "还原被替换的文件并清除启动参数。",
  "game.uninstall.action": "从此游戏移除",

  // Defaults for new games.
  "defaults.title": "新游戏默认设置",
  "defaults.dll.label": "默认加载用 DLL",

  // In-game direct controls.
  "controls.title": "游戏内控制",
  "controls.openPanel": "打开 OptiScaler 设置面板",
  "controls.closePanel": "关闭 OptiScaler 设置面板",
  "controls.showStats": "显示 OptiScaler 性能统计",
  "controls.hideStats": "隐藏 OptiScaler 性能统计",
  "controls.needsBuild": "请先用直接控制版构建启动游戏。",

  // Shared wording.
  "common.retry": "重试",

  // Toasts.
  "toast.controls.panelOpened": "OptiScaler 设置面板已打开。",
  "toast.controls.panelClosed": "OptiScaler 设置面板已关闭。",
  "toast.controls.statsShown": "已显示 OptiScaler 性能统计。",
  "toast.controls.statsHidden": "已隐藏 OptiScaler 性能统计。",
  "toast.install.success": "已在 {count} 个文件夹中安装为 {dll}，并设置启动参数。",
  "toast.uninstall.success": "已从 {count} 个文件夹中移除。",
  "toast.dllChanged": "现在以 {dll} 加载。",
  "toast.buildReady": "构建 {version} 已就绪。",
  "toast.updateAvailable": "有可用更新：{version}",
  "toast.latest": "当前已是最新构建。",
  "toast.refresh.someFailed": "已更新 {count} 个游戏，{failed} 个失败。",
  "toast.refresh.success": "已更新 {count} 个游戏。",

  // Real loader DLL labels. The file name inside every label is preserved.
  "dll.dxgi": "dxgi.dll（默认，适用于大多数 DX11/DX12 游戏）",
  "dll.winmm": "winmm.dll（dxgi 与其他 MOD 冲突时使用）",
  "dll.version": "version.dll（常见替代）",
  "dll.dbghelp": "dbghelp.dll（游戏拒绝其他 DLL 时使用）",
  "dll.d3d12": "d3d12.dll（仅 DX12）",
  "dll.wininet": "wininet.dll（最后备选）",
  "dll.winhttp": "winhttp.dll（最后备选）",

  // Overlay backend errors (main.py) shown through the same toast path.
  "overlay.error.noGame": "没有已安装的游戏与此 App ID 匹配。",
  "overlay.error.notConfirmed": "OptiScaler 核心未确认此更改。请在游戏运行时重试。",
  "overlay.error.unsupported": "不支持的 OptiScaler 控制请求。",

  // Errors the frontend itself raises and shows raw through the toast path.
  "errors.launchOptionsRefused": "Steam 未能应用启动参数更改",
};

export default zhCN;
