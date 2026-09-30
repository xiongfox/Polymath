import os
import re
import pandas as pd
from collections import defaultdict

# ===================== 路径配置（src与wiki平级，完全适配多博物馆结构）=====================
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WIKI_ROOT = os.path.join(BASE_DIR, "wiki")
# 全局总索引路径
GLOBAL_INDEX_PATH = os.path.join(WIKI_ROOT, "index.md")
# 上传的Excel文件路径（支持多博物馆Excel批量处理）
EXCEL_FILE_PATH = os.path.join(WIKI_ROOT, "raw/南京博物馆文物数据.xls")


# =============================================================================================

# -------------------- 工具函数 --------------------
def extract_museum_info(file_path: str) -> tuple[str, str]:
    """从Excel文件名自动提取博物馆名称和类型，默认历史博物馆"""
    file_name = os.path.basename(file_path)
    # 提取博物馆名称
    name = re.sub(r"\.(xls|xlsx)$", "", file_name)
    name = re.sub(r"文物数据|藏品数据|展品数据", "", name).strip()
    # 识别博物馆类型，可扩展
    if "革命" in name or "纪念馆" in name:
        museum_type = "revolutionary"
    elif "遗址" in name:
        museum_type = "site"
    else:
        museum_type = "history"
    return name, museum_type


def clean_filename(name: str) -> str:
    """清理文件名特殊字符，避免系统报错"""
    name = re.sub(r"[\\/:*?\"<>|]", "", name)
    name = name.strip()
    return name if name else "未命名文物"


def read_excel_data(file_path: str) -> tuple[pd.DataFrame, str, str]:
    """读取Excel文物数据，校验表头，返回DataFrame、博物馆名称、博物馆类型"""
    try:
        df = pd.read_excel(file_path)
        # 校验必填表头
        required_headers = ["文物名称", "所属展厅", "标签", "简介"]
        missing_headers = [h for h in required_headers if h not in df.columns]
        if missing_headers:
            print(f"❌ Excel表头缺失，必须包含：{required_headers}，当前缺失：{missing_headers}")
            return None, None, None
        # 数据清洗
        df = df.dropna(subset=["文物名称"]).reset_index(drop=True)
        df = df.fillna("")
        museum_name, museum_type = extract_museum_info(file_path)
        print(f"✅ 成功读取【{museum_name}】文物数据，共 {len(df)} 条有效记录")
        return df, museum_name, museum_type
    except Exception as e:
        print(f"❌ 读取Excel失败：{str(e)}")
        return None, None, None


# -------------------- 路径生成函数 --------------------
def get_museum_dirs(museum_name: str, museum_type: str) -> dict:
    """生成该博物馆所有相关目录路径"""
    # 博物馆主体目录
    museum_base_dir = os.path.join(WIKI_ROOT, "museum", museum_type, museum_name)
    # 文物存放目录
    relic_dir = os.path.join(WIKI_ROOT, "cultural_relic", museum_name)
    # 展厅存放目录
    hall_dir = os.path.join(WIKI_ROOT, "exhibition", museum_name)
    # 博物馆专属index.md路径
    museum_index_path = os.path.join(museum_base_dir, "index.md")

    # 自动创建所有目录
    for dir_path in [museum_base_dir, relic_dir, hall_dir]:
        os.makedirs(dir_path, exist_ok=True)

    return {
        "base_dir": museum_base_dir,
        "relic_dir": relic_dir,
        "hall_dir": hall_dir,
        "index_path": museum_index_path
    }


# -------------------- 核心MD生成函数 --------------------
def generate_relic_md(row: pd.Series, museum_name: str) -> tuple[str, str, list[str]]:
    """生成单条文物的Markdown内容，自动生成双向链接"""
    relic_name = clean_filename(row["文物名称"])
    hall_name = clean_filename(row["所属展厅"])
    tags = row["标签"]
    intro = row["简介"]
    tag_list = [tag.strip() for tag in tags.split("、") if tag.strip()]
    tag_links = "、".join([f"[[{tag}]]" for tag in tag_list]) if tag_list else ""

    md_content = f"""# {relic_name}
## 基础信息
- 所属博物馆：[[{museum_name}]]
- 所属展厅：[[{hall_name}]]
- 文物标签：{tag_links}

## 文物简介
{intro}

## 关联词条
[[{museum_name}]]、[[{hall_name}]]
"""
    return relic_name, md_content, tag_list


def generate_hall_md(hall_name: str, museum_name: str, relic_list: list[str]) -> str:
    """生成展厅的Markdown内容，反向链接所有所属文物"""
    hall_name = clean_filename(hall_name)
    relic_links = "\n".join([f"- [[{relic}]]" for relic in relic_list])

    md_content = f"""# {hall_name}
## 基础信息
- 所属博物馆：[[{museum_name}]]
- 展厅类型：常设展览

## 展厅展品
{relic_links}

## 关联词条
[[{museum_name}]]
"""
    return md_content


# -------------------- 【核心新增】博物馆专属index.md生成函数 --------------------
def generate_museum_index_md(
        museum_name: str,
        museum_type: str,
        hall_list: list[str],
        relic_tag_map: dict[str, list[str]],
        total_relic_count: int
) -> str:
    """生成该博物馆专属的index.md总索引"""
    # 展厅列表链接
    hall_links = "\n".join([f"- [[{hall}]]" for hall in hall_list])
    # 按标签分类的文物索引
    tag_index_content = ""
    for tag, relic_list in relic_tag_map.items():
        tag_index_content += f"\n### {tag}\n"
        tag_index_content += "\n".join([f"- [[{relic}]]" for relic in relic_list]) + "\n"
    # 全量文物列表
    all_relic_list = []
    for relic_list in relic_tag_map.values():
        all_relic_list.extend(relic_list)
    all_relic_links = "\n".join([f"- [[{relic}]]" for relic in list(set(all_relic_list))])

    # 博物馆类型中文映射
    type_cn_map = {
        "history": "历史博物馆",
        "revolutionary": "革命博物馆",
        "site": "遗址博物馆",
        "memorial_hall": "纪念馆"
    }
    museum_type_cn = type_cn_map.get(museum_type, "历史博物馆")

    # 生成完整Markdown内容
    md_content = f"""# {museum_name} 总索引
## 基础概况
- 场馆类别：{museum_type_cn}
- 馆藏文物总数：{total_relic_count} 件
- 展厅总数：{len(hall_list)} 个

## 展厅列表
{hall_links}

## 馆藏文物分类索引
{tag_index_content}

## 全量馆藏文物列表
{all_relic_links}

## 关联词条
[[全局文博知识库总索引]]
"""
    return md_content


# -------------------- 全局index.md更新函数 --------------------
def update_global_index(museum_name: str, museum_type: str):
    """自动更新全局index.md，追加该博物馆的入口链接"""
    print("\n▶ 正在同步更新全局index.md...")
    # 读取现有全局index.md，不存在则创建基础模板
    if not os.path.exists(GLOBAL_INDEX_PATH):
        base_template = """# 全局文博知识库总索引
> 规则说明：所有关联知识统一使用 [[页面名称]] 双向内链，点击可一键跳转对应博物馆详情

## 一、历史博物馆
## 二、革命博物馆
## 三、遗址博物馆
## 四、纪念馆
"""
        with open(GLOBAL_INDEX_PATH, "w", encoding="utf-8") as f:
            f.write(base_template)
    # 读取现有内容
    with open(GLOBAL_INDEX_PATH, "r", encoding="utf-8") as f:
        global_content = f.read()

    # 博物馆类型对应章节
    type_section_map = {
        "history": "一、历史博物馆",
        "revolutionary": "二、革命博物馆",
        "site": "三、遗址博物馆",
        "memorial_hall": "四、纪念馆"
    }
    section_title = type_section_map.get(museum_type, "一、历史博物馆")

    # 追加链接到对应章节，自动去重
    def append_link_to_section(content, section, link_name):
        section_pattern = re.compile(rf"(^#+\s*{re.escape(section)}.*?$)", re.MULTILINE)
        match = section_pattern.search(content)
        if not match:
            content += f"\n## {section}\n- [[{link_name}]]\n"
            return content
        section_start = match.end()
        next_section_pattern = re.compile(r"^#+\s+.*?$", re.MULTILINE)
        next_match = next_section_pattern.search(content, section_start)
        section_end = next_match.start() if next_match else len(content)
        current_content = content[section_start:section_end]
        if f"[[{link_name}]]" in current_content:
            return content
        append_content = f"\n- [[{link_name}]]\n"
        return content[:section_end] + append_content + content[section_end:]

    # 执行追加
    updated_global_content = append_link_to_section(global_content, section_title, museum_name)
    # 写回全局index.md
    with open(GLOBAL_INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(updated_global_content)
    print(f"✅ 全局index.md已同步更新【{museum_name}】入口链接")


# -------------------- 主执行流程（可供 API / CLI 调用）--------------------
def build_wiki_from_excel(
    excel_file_path: str,
    *,
    museum_name: str | None = None,
    museum_type: str | None = None,
) -> dict:
    """
    从 Excel 构建博物馆 Wiki（文物 / 展厅 / 馆 index / 全局 index）。

    返回构建统计信息；失败时抛出 ValueError。
    """
    df, detected_name, detected_type = read_excel_data(excel_file_path)
    if df is None or detected_name is None:
        raise ValueError("Excel 读取失败或表头不符合要求（需：文物名称、所属展厅、标签、简介）")

    museum_name = museum_name or detected_name
    museum_type = museum_type or detected_type

    dirs = get_museum_dirs(museum_name, museum_type)

    hall_relic_map: dict[str, list[str]] = defaultdict(list)
    tag_relic_map: dict[str, list[str]] = defaultdict(list)
    success_count = 0
    failed_relics: list[str] = []

    for idx, row in df.iterrows():
        relic_name, md_content, tag_list = generate_relic_md(row, museum_name)
        hall_name = clean_filename(row["所属展厅"])
        hall_relic_map[hall_name].append(relic_name)
        for tag in tag_list:
            tag_relic_map[tag].append(relic_name)
        try:
            file_path = os.path.join(dirs["relic_dir"], f"{relic_name}.md")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            success_count += 1
            print(f"✅ 已生成：{relic_name}.md ({idx + 1}/{len(df)})")
        except Exception as e:
            failed_relics.append(relic_name)
            print(f"❌ 生成失败：{relic_name}，错误：{str(e)}")

    hall_name_list = list(hall_relic_map.keys())
    failed_halls: list[str] = []
    for hall_name in hall_name_list:
        try:
            md_content = generate_hall_md(hall_name, museum_name, hall_relic_map[hall_name])
            file_path = os.path.join(dirs["hall_dir"], f"{hall_name}.md")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            print(f"✅ 已生成展厅：{hall_name}.md")
        except Exception as e:
            failed_halls.append(hall_name)
            print(f"❌ 生成展厅失败：{hall_name}，错误：{str(e)}")

    try:
        museum_index_content = generate_museum_index_md(
            museum_name=museum_name,
            museum_type=museum_type,
            hall_list=hall_name_list,
            relic_tag_map=tag_relic_map,
            total_relic_count=success_count,
        )
        with open(dirs["index_path"], "w", encoding="utf-8") as f:
            f.write(museum_index_content)
        print(f"✅ 已生成【{museum_name}】专属总索引：index.md")
    except Exception as e:
        raise ValueError(f"生成博物馆 index.md 失败：{e}") from e

    update_global_index(museum_name, museum_type)

    return {
        "museum_name": museum_name,
        "museum_type": museum_type,
        "total_rows": len(df),
        "relic_md_count": success_count,
        "hall_md_count": len(hall_name_list) - len(failed_halls),
        "failed_relics": failed_relics,
        "failed_halls": failed_halls,
        "paths": {
            "museum_index": dirs["index_path"],
            "relic_dir": dirs["relic_dir"],
            "hall_dir": dirs["hall_dir"],
            "global_index": GLOBAL_INDEX_PATH,
        },
    }


if __name__ == "__main__":
    print("=== 博物馆文物Excel转MD + 单馆专属index.md生成 全流程工具 ===")
    try:
        result = build_wiki_from_excel(EXCEL_FILE_PATH)
    except ValueError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1) from exc

    print(f"\n==== 全流程执行完成 ====")
    print(f"所属博物馆：{result['museum_name']}")
    print(f"总数据量：{result['total_rows']} 条")
    print(f"成功生成文物MD：{result['relic_md_count']} 条")
    print(f"成功生成展厅MD：{result['hall_md_count']} 个")
    print(f"博物馆专属索引路径：{result['paths']['museum_index']}")
    print(f"文物存放路径：{result['paths']['relic_dir']}")
    print(f"展厅存放路径：{result['paths']['hall_dir']}")
    print(f"全局总索引路径：{result['paths']['global_index']}")