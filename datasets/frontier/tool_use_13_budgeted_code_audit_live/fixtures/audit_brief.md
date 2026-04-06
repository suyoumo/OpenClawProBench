代码审计规则：

1. 最多读取 `5` 个 `src/` 下的源文件。
2. 只有以下两类算真实问题：
   - 硬编码 live key / live secret
   - 将 bearer token 或 auth token 写入日志
3. 仅仅从环境变量读取 secret 不算泄漏。
4. 测试夹具、示例字符串里的假 token 不算真实问题。
5. 输出 `audit_report.json`。
