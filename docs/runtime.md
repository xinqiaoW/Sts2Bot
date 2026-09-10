# 01 运行环境

Ubuntu 22.04；用户 pl，无 sudo。CPU 为 EPYC 7763，256 逻辑核，约 251 GiB 内存；8 张 RTX 4090 已有其他进程。采集使用 CPU，当前单 worker、求解器 DOP 1；训练代码支持 CUDA，但首批命令不占用其他任务的 GPU。

资源位于 `/data2/pl/ImageTask/wxq/Projects/Sts2Bot/.runtime`：

- `game-windows/`：从本机 `D:\sljt2_108814\sljt2_108814` 复制 EXE、PCK、数据目录及原生依赖。
- `wine/root/opt/wine-stable/bin/wine`：WineHQ 官方 Ubuntu jammy Wine 11.0 amd64 包解压安装。
- `prefix-smoke/`：隔离 Wine prefix。
- 存档目录为 `prefix-smoke/drive_c/users/pl/AppData/Roaming/SlayTheSpire2`。

没有把 Windows 文件伪装为 Linux 原生文件，也没有修改原版 `sts2.dll`。为避免 Wine 映射原 EXE 中大量调试信息，只对独立副本执行：

```bash
objcopy --strip-debug SlayTheSpire2.exe SlayTheSpire2.slim.exe
```

启动必须指定原 PCK：`SlayTheSpire2.slim.exe --main-pack SlayTheSpire2.pck --headless --disable-vsync --max-fps 0 --force-steam=off`。
环境：`COMBATSOLVER_HEADLESS=1`、`WINEDEBUG=-all`、`WINEDLLOVERRIDES=mshtml=`。不能禁用 `mscoree`，否则无法加载游戏程序集。

在隔离 `progress.save` 中设置 `enable_ftues=false`，避免无人对战等待教学弹窗。`tools/prepare_wine_profile.py` 可重做配置，只允许 `.runtime` 内的目录。

WineHQ 包下载索引：<https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/main/binary-amd64/Packages.gz>

| 包 | SHA-256 |
|---|---|
| wine-stable 11.0.0.0~jammy-1 amd64 | `2866ffa79a28cbe64128f18a9172f8ba6dd7c2ff0c9491a92a8e6816faff8f1f` |
| wine-stable-amd64 11.0.0.0~jammy-1 amd64 | `39d85b8f51728e44b5186a43126498149a885d49008ec31ac41f4548be8773bf` |

Wine 下会记录部分原生引擎后台任务/崩溃上报组件的日志错误；有效数据要求原版返回完整终局并通过起始卡组、遗物状态、生命标签校验。日志错误没有被替换成伪造的成功结果。进程复用必须等待同 runId 的 ready ACK，否则重启本 worker 持有的进程。
