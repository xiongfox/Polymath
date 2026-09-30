# Claude Code 文博LLM Wiki 强制工作规范
## 基础前置规则
1. 进入项目首先完整通读 `index.md` 全局知识库索引，严格遵循目录层级、分类定义、存储路径执行所有操作
2. 严格区分素材库与正式知识库：仅处理正式目录内容，**禁止读取、修改、引用 ./raw/ 原始草稿文件**
3. 所有新建Wiki页面统一使用标准Markdown格式，知识关联全部采用 `[[页面名称]]` 双向内链语法
4. 文博内容坚守史实严谨性，不杜撰历史、馆藏信息、人物事迹、遗址考古资料，存异说仅客观记录

## 目录存放硬性标准
1. 场馆类
- 革命博物馆、革命纪念馆 → museum/revolutionary/
- 地方通史/历史博物馆 → museum/history/
- 考古遗址博物馆 → museum/site/
- 人物/事件专题纪念馆 → museum/memorial_hall/
2. 事件类
- 红色革命事件 → history_event/red_event/
- 古代历史事件 → history_event/ancient_event/
3. 人物类
- 革命先烈、革命志士 → historical_figure/revolutionary_hero/
- 古代历史名人 → historical_figure/ancient_celebrity/
4. 文物遗存类
- 革命实物文物 → cultural_relic/red_relic/
- 出土传世古文物 → cultural_relic/ancient_relic/
- 革命旧址、会议旧址 → relic_site/revolutionary_site/
- 古遗址、古城址 → relic_site/ancient_site/
5. 展陈研学内容统一存入 exhibition/ 目录

## Ingest 入库执行规范
1. 调用本地qwen3:8b模型解析raw内文档，自动匹配上述分类生成对应Wiki页面
2. 页面固定结构：基础概况+历史脉络+核心内容+价值意义+关联词条
3. 完成入库后，自动在index.md对应分类下追加 `[[页面文件名]]` 导航链接
4. 入库操作日志统一写入 log.md，记录时间、来源文件、存储路径

## 知识库查询规范
1. 接收提问后优先依据index.md锁定知识所属分类与文件夹
2. 逐层读取对应目录下Wiki页面，串联内链整合完整答案
3. 信息缺失直接如实说明，禁止幻觉编造文博相关内容
4. 回答可标注信息来源Wiki页面名称

## 脚本开发规范
1. 编写Python入库/查询脚本，默认对接本地Ollama qwen3:8b
2. 脚本自带目录自动创建、文件编码utf-8、JSON清洗容错、异常捕获
3. 批量处理仅筛选md、txt格式文档，自动跳过无效文件