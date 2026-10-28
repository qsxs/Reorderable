# Reorderable 3.1.0 OHOS 独立 producer

本入口直接编译同一 Fork 中 `reorderable/src/commonMain/kotlin` 的全部 9 份原源，不复制、裁剪或改写生产源码。上游 [Calvin-LL/Reorderable v3.1.0](https://github.com/Calvin-LL/Reorderable/commit/66de5751227c440bcdbd63acc94999231ed67487) 的 sources JAR、POM、GMM、构建声明与 Apache-2.0 LICENSE 原件及 SHA-256 保存在 `vendor/`、`legal/` 和 `source-inputs.json`；上游作者 Calvin Liang 及仓库历史保留。

独立根坐标为 `io.github.qsxs.cpf.reorderable:reorderable:3.1.0-cpf11-preview-<sourceSHA12>-<runID>-<attempt>`。固定 Kotlin/Native 与 Compose compiler `2.4.20-0.1.0-08`、Compose `1.12.0-0.1.0-11`、Gradle 9.5.0 和 JDK 17。三个原有 Compose runtime/animation/foundation 依赖保持 `implementation`；标准 KGP 编译 metadata、OHOS x64 和 arm64。全部 9 份源码、原来源、发布图和已有 Native metadata/IR 签名清单均参与阶段检查，不以调用点裁剪 API。

Linux x86_64 工作流可按顺序执行 `Prepare`、`Tasks`、`Resolve`、`Metadata`、`NativeX64`、`NativeArm64`、`Publish`、`Verify`。例如以环境变量显式提供输入：

```sh
python -B ohos/ReorderablePort.py Prepare --source-sha "$SOURCE_SHA" --run-id "$RUN_ID" --run-attempt "$RUN_ATTEMPT" --work "$WORK_DIR" --repository "$STAGING_DIR" --tooling "$TOOLING_DIR" --native-home "$NATIVE_HOME"
```

后续阶段使用相同参数，依次将 `Prepare` 替换为对应阶段名；`--native-home` 是已核对版本的 Kotlin/Native 目录，`--tooling` 指向锁定版本的公共工具仓根，省略时从固定公开归档取对应文件并校验。工作与发布目录由调用方显式指定，Gradle/Konan/temp 均隔离在工作目录，输出仅为独立 staging；两目录不得等于或包含配方根，位于配方内时首次须使用不含配方文件的空目录，已有同版本目录会拒绝覆盖。首次 Prepare 对 `source-manifest.json`、`provenance.json` 和 `prepared.json` 使用独占创建，不覆盖已有记录；已准备目录的重复调用保持原行为。后续工作流只需提供完整 source SHA、run id/attempt 和上述目录，不需要 App、MaterialKolor helper 或本机缓存。

## 生产、发布与公开消费编译

[Fork source `85707894c99f8ce4c3fe10a84c870c71cee0b10b`](https://github.com/qsxs/Reorderable/commit/85707894c99f8ce4c3fe10a84c870c71cee0b10b) 经 [producer 40715768847/1](https://github.com/qsxs/cpf-port-tooling/actions/runs/40715768847/attempts/1) 完成 9 份原源的 metadata、OHOS x64、arm64 生产，工作流提交 B 为 `8fd0a63cf246b2b8e90132b091506b49c9ebfb26`。双 ABI 各核验 43 个 Native metadata 名称与 4 条枚举生成 IR 签名。Runner 物理源码、编译器插件与工具输入已清理；记录与来源锁匹配，但无法在本机重新哈希这些 runner 输入。

已发布根 GAV：`io.github.qsxs.cpf.reorderable:reorderable:3.1.0-cpf11-preview-85707894c99f-40715768847-1`；临时 Maven 根 `https://qsxs.github.io/cpf-maven/`（[根 POM](https://qsxs.github.io/cpf-maven/io/github/qsxs/cpf/reorderable/reorderable/3.1.0-cpf11-preview-85707894c99f-40715768847-1/reorderable-3.1.0-cpf11-preview-85707894c99f-40715768847-1.pom)）。[Pages 制品提交 `3d5fe28dcc5b`](https://github.com/qsxs/cpf-maven/commit/3d5fe28dcc5b3a4cf326a8c413e649d7e0e2746a) 的 140 个文件、565,377 字节与 staging 匿名核验全部对齐；期间 15 次传输超时后重试，最终 140/140 匹配。

[consumer 40719398970/1](https://github.com/qsxs/cpf-port-tooling/actions/runs/40719398970/attempts/1) 使用工作流提交 B `2f30528fb9e0a90164d111788d701fd177897e63` 和 Gradle 9.5.0，完成同一 1328B LazyList/LazyGrid 状态、item 与两种拖拽 handle 探针的 common metadata、OHOS x64 和 arm64 真实编译；12 个不同公开对象均首次 HTTP 成功并与 staging 对齐，三配置选择正确 root/leaf，Native Klib SHA 和 IR 已独立核对。Metadata 转换 Klib 原件未上传，不能在本机独立重哈希其内部成员。

Gradle 8 消费、link、runtime、设备和 Android/iOS 回归未验证，App 引用尚未切换。历史 x64 HAP 结果不能代替本次独立运行验收。
