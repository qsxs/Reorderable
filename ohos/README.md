# Reorderable 3.1.0 OHOS 独立 producer

本入口直接编译同一 Fork 中 `reorderable/src/commonMain/kotlin` 的全部 9 份原源，不复制、裁剪或改写生产源码。上游 [Calvin-LL/Reorderable v3.1.0](https://github.com/Calvin-LL/Reorderable/commit/66de5751227c440bcdbd63acc94999231ed67487) 的 sources JAR、POM、GMM、构建声明与 Apache-2.0 LICENSE 原件及 SHA-256 保存在 `vendor/`、`legal/` 和 `source-inputs.json`；上游作者 Calvin Liang 及仓库历史保留。

独立根坐标为 `io.github.qsxs.cpf.reorderable:reorderable:3.1.0-cpf11-preview-<sourceSHA12>-<runID>-<attempt>`。固定 Kotlin/Native 与 Compose compiler `2.4.20-0.1.0-08`、Compose `1.12.0-0.1.0-11`、Gradle 9.5.0 和 JDK 17。三个原有 Compose runtime/animation/foundation 依赖保持 `implementation`；标准 KGP 编译 metadata、OHOS x64 和 arm64。全部 9 份源码、原来源、发布图和已有 Native metadata/IR 签名清单均参与阶段检查，不以调用点裁剪 API。

Linux x86_64 工作流可按顺序执行 `Prepare`、`Tasks`、`Resolve`、`Metadata`、`NativeX64`、`NativeArm64`、`Publish`、`Verify`。例如以环境变量显式提供输入：

```sh
python -B ohos/ReorderablePort.py Prepare --source-sha "$SOURCE_SHA" --run-id "$RUN_ID" --run-attempt "$RUN_ATTEMPT" --work "$WORK_DIR" --repository "$STAGING_DIR" --tooling "$TOOLING_DIR" --native-home "$NATIVE_HOME"
```

后续阶段使用相同参数，依次将 `Prepare` 替换为对应阶段名；`--native-home` 是已核对版本的 Kotlin/Native 目录，`--tooling` 指向锁定版本的公共工具仓根，省略时从固定公开归档取对应文件并校验。工作与发布目录由调用方显式指定，Gradle/Konan/temp 均隔离在工作目录，输出仅为独立 staging；两目录不得等于或包含配方根，位于配方内时首次须使用不含配方文件的空目录，已有同版本目录会拒绝覆盖。后续工作流只需提供完整 source SHA、run id/attempt 和上述目录，不需要 App、MaterialKolor helper 或本机缓存。

当前仅为配方实现：Tasks、Resolve、metadata、双 Native、Publish 和 Verify 均未运行；link、runtime、设备和 Android/iOS 回归也未验证。独立公共发布及消费需后续另行验收。
