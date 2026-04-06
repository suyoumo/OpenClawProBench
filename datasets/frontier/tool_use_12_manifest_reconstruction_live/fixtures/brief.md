今晚发布清单的重建规则：

1. 从 `manifests/base_manifest.json` 作为初始清单开始。
2. 读取 `patches/patch_01.md`，把新增服务并入清单。
3. 如果某个服务出现在 `rollback_notes.md`，则它不应出现在最终清单中。
4. 如果 `hotfixes.txt` 覆盖了服务版本，最终版本以 hotfix 为准。
5. 忽略 `archive/` 下的历史噪音文件。

输出 `release_manifest.json`。
