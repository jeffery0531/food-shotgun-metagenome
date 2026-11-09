# 食品微生物 shotgun 宏基因组数据

这个仓库汇总了公开数据库中**食品样本的 shotgun 宏基因组测序数据**（原始 reads）。里面有一张可以筛选的数据清单，和两个脚本：一个按清单下载数据，一个更新清单。

清单版本：2026-11-09

## 一、这里有什么

| 范围 | run 数 | 样本数 | 数据量（压缩后的 FASTQ） |
|---|---|---|---|
| **推荐使用** | 11,184 | 10,005 | 39.3 TB |
| 清单全部 | 18,832 | — | 54.8 TB |

"run"是一次测序得到的一组文件，编号如 SRR…、ERR…、CRR…。一个样本可能有多个 run。

数据来源：

- **cFMD**：意大利 Segata 实验室人工整理的食品宏基因组数据库（Carlino et al., *Cell* 2024），食品分类最可靠。
- **NCBI SRA / ENA / DDBJ**：国际三大测序数据库，内容互相同步。本清单通过 ENA 查询。推荐数据中有 10,402 个 run（32.6 TB）来自这里。
- **GSA**：国家基因组科学数据中心（北京），不与国际库同步，收录了不少国内发酵食品研究，如白酒大曲。推荐数据中有 782 个 run（6.6 TB）来自这里。

推荐数据按食品类别统计（`food_category` 列；下载时用英文类别名）：

| 类别（英文名） | 中文 | run 数 | 数据量 |
|---|---|---|---|
| dairy | 乳制品 | 4,103 | 12.3 TB |
| meat | 肉类 | 1,067 | 3.8 TB |
| alcohol | 酒类（含白酒大曲） | 749 | 3.3 TB |
| fruits_and_vegetables | 果蔬 | 1,093 | 3.0 TB |
| fish | 鱼和海鲜 | 241 | 2.4 TB |
| fermented_fruits_and_vegetables | 发酵果蔬（泡菜、酸菜等） | 501 | 1.4 TB |
| fermented_beverages | 发酵饮料（水开菲尔、康普茶、醋等） | 704 | 1.3 TB |
| fermented_grains | 发酵谷物（酸面团、曲等） | 167 | 0.6 TB |
| fermented_meat | 发酵肉制品（萨拉米等） | 157 | 0.6 TB |
| fermented_legumes | 发酵豆制品（酱油、豆酱、纳豆等） | 151 | 0.5 TB |
| other | 其他（蜂蜜、蛋等） | 477 | 0.4 TB |
| fermented_seeds | 发酵可可、咖啡 | 119 | 0.4 TB |
| cereals_and_legumes | 谷物和豆类（未发酵） | 99 | 0.3 TB |
| fermented_fish | 发酵鱼制品（鱼露等） | 31 | 0.1 TB |
| probiotics | 益生菌产品 | 36 | 0.04 TB |
| fermented_tubers_and_roots | 发酵块根（木薯等） | 24 | 0.02 TB |
| （空） | 无法判断类别 | 1,465 | 8.8 TB |

## 二、文件夹结构

```
food-shotgun-metagenome/
├── README.md                      本说明
├── LICENSE                        脚本的许可（MIT）
├── catalog/
│   ├── food_shotgun_runs.csv      数据清单（Excel 打开这个）
│   ├── food_shotgun_runs.tsv      同一份清单（程序读取用，制表符分隔）
│   ├── summary.md                 统计汇总（英文）
│   └── cfmd_unresolved.tsv        cFMD 中没有公开下载编号的 166 个样本
├── scripts/
│   ├── download_reads.py          按清单下载 FASTQ
│   └── build_catalog.py           生成 / 更新清单
└── raw/                           查询缓存（不在仓库里，第一次更新清单时自动生成）
```

## 三、快速上手

先下载本仓库：在 [GitHub 页面](https://github.com/jeffery0531/food-shotgun-metagenome)点绿色的 **Code** 按钮 → **Download ZIP**，解压即可；会用 git 的话也可以运行 `git clone https://github.com/jeffery0531/food-shotgun-metagenome.git`。下面的命令都在解压后的文件夹里运行。

### 1. 用 Excel 浏览清单

打开 `catalog/food_shotgun_runs.csv`，一行是一个 run。常用操作：

- 筛选 `recommended` = `yes`，就是推荐使用的数据；
- 按 `food_category`（大类）、`food_type`（具体食品）、`country`（国家）筛选；
- `isolation_source`、`sample_title`、`study_title` 是原始的样本和项目描述，可以用来进一步判断。

每列的含义见第五节。

### 2. 预览下载量（不会真的下载）

需要 Python 3.9 以上和 curl（macOS、Linux 自带；Windows 上把下面的 `python3` 换成 `python`）。在本文件夹中运行：

```bash
python3 scripts/download_reads.py --out /大硬盘路径/food_reads --dry-run
```

屏幕上会显示要下载多少个 run、多少数据、按类别的统计，以及目标位置的剩余空间。

### 3. 开始下载

去掉 `--dry-run` 就会开始下载，例如只下载乳制品：

```bash
python3 scripts/download_reads.py --out /大硬盘路径/food_reads --category dairy
```

建议第一次先加 `--limit 5` 试下 5 个，看看速度再决定。

## 四、下载脚本用法

### 选择要下载的数据

| 想要 | 参数 |
|---|---|
| 全部推荐数据 | 不加筛选参数 |
| 某几类食品 | `--category dairy,meat`（英文类别名见第一节） |
| 只要某个数据库的 | `--archive GSA` 或 `--archive INSDC` |
| 包括"待核对"的数据 | `--tier core,review`（见第六节） |
| 自己挑的 run | `--runs my_runs.txt`，文件中一行一个 run 编号。可以在 Excel 里筛选后复制 `run_accession` 列 |
| 先试几个 | `--limit 5` |
| 同时下载的文件数 | `--jobs 4`（默认 4） |
| 只导出下载地址，用别的工具下载 | `--export urls.tsv` |

用 `--runs` 时，列表里的 run 都会下载（没有文件的除外），不受第六节的标记影响。

### 下载过程

- 文件保存在 `<输出目录>/<run 编号>/` 下。
- **可以随时中断**：再运行同一条命令就会从断点继续，已经下完的文件自动跳过。
- 每个文件下完都会核对 MD5 校验码，不一致会自动重新下载。
- 每次下载都记录在 `<输出目录>/download_log.tsv`。
- 剩余空间不够时脚本会拒绝开始；确认没问题可以加 `--force`。

### 下载后的文件

- 双端测序有两个文件：`_1` / `_2`（国际库）或 `_f1` / `_r2`（GSA）。部分国际库 run 还有第三个文件，里面是没有配对的 reads。单端测序只有一个文件。
- 有 11 个 GSA run 的文件是 BAM 格式（未比对的 reads），可以用 `samtools fastq` 转成 FASTQ。
- 带 `long_read` 标记的是 Nanopore / PacBio 长读长数据，需要用长读长的工具分析。

### 存储和网速

- 推荐数据共约 39 TB，请在服务器或大容量存储上下载，或者只下需要的类别。
- 下载速度取决于网络。2026 年 11 月在整理清单的电脑上实测：ENA 约 0.03 MB/s；GSA 在 0.01–0.7 MB/s 之间，而且大约每分钟断线一次（脚本会自动续传）。速度太慢时可以：
  - 换到网络更好的服务器上运行；
  - 用 `--export` 导出地址，改用其他下载工具（如 aria2、Aspera）；
  - 国际库的数据也可以从 NCBI 在 AWS 上的镜像下载（.sra 格式，需要用 SRA Toolkit 的 `fasterq-dump` 转成 FASTQ）。同一台电脑上实测约 1.35 MB/s，比 ENA 快得多。

## 五、清单各列的含义

| 列 | 含义 |
|---|---|
| `run_accession` | run 编号。SRR / ERR / DRR 来自国际库，CRR 来自 GSA |
| `recommended` | `yes` = 推荐使用，也是下载脚本默认下载的范围 |
| `archive` | `INSDC`（NCBI / ENA / DDBJ）或 `GSA` |
| `tier` | 可信度分档：core / review / keyword（见第六节） |
| `sources` | 由哪个来源找到：`cfmd`、`ena_taxon`、`ena_keyword`、`gsa_taxon` |
| `flags` | 注意事项标记（见第六节） |
| `food_category` / `food_type` | 食品大类 / 具体食品（具体食品只有 cFMD 样本有） |
| `food_category_source` | `cfmd` = 人工分类；`guess` = 根据描述自动推测，可能有误 |
| `fermented` | F = 发酵，NF = 非发酵（只有 cFMD 样本有） |
| `sample_accession` / `study_accession` | 样本编号 / 项目编号（PRJNA、PRJEB、PRJCA 等） |
| `scientific_name` | 数据库中登记的名称，如 food metagenome |
| `library_strategy` / `library_source` | 测序策略 / 文库来源。shotgun 一般是 WGS / METAGENOMIC |
| `instrument_platform` / `instrument_model` | 测序平台 / 型号 |
| `read_count` / `base_count` | reads 数 / 碱基数 |
| `fastq_bytes` | 文件总大小（字节） |
| `isolation_source` / `sample_title` / `study_title` | 样本来源、样本名、项目名（原始描述） |
| `country` / `collection_date` / `first_public` | 国家 / 采样日期 / 公开日期 |
| `cfmd_dataset` / `cfmd_sample_id` | 在 cFMD 中的数据集和样本名 |
| `keyword_hit` | keyword 档命中的关键词 |
| `fastq_urls` / `fastq_md5` / `fastq_file_bytes` | 每个文件的下载地址 / MD5 / 大小，多个文件用 `;` 分隔 |

## 六、分档和标记

### 分档（`tier` 列）

- **core（核心）**：在 cFMD 中，或者在数据库中登记为食品类宏基因组（food、food fermentation、milk、dairy、meat、wine、honey、grain、egg、food contamination metagenome）。
- **review（待核对）**：登记为发酵、食品生产、酒厂、青贮、屠宰场宏基因组。其中混有非食品样本，如工业发酵、烟叶发酵、加工厂环境，使用前请按项目核对。例如 GSA 项目 CRA030470（463 个 run）的样本信息不明确。
- **keyword（关键词）**：只是样本描述里出现了食品相关的词（如 cheese、koji），可信度最低。

### 标记（`flags` 列）

带 * 的标记会让这个 run 不进入推荐数据。

| 标记 | 含义 |
|---|---|
| `low_depth`* | 样本数据量太小（少于 0.2 Gbp），常常是被误标成 shotgun 的扩增子数据 |
| `tiny_run`* | 单个 run 极小（少于 1000 万碱基），通常是附带的残缺数据 |
| `no_fastq`* | 数据库没有提供 FASTQ 文件 |
| `cfmd_filtered`* | 被 cFMD 整理者排除 |
| `enrichment`* | 描述中提到富集培养（enrichment、broth），是病原检测用的培养物，不代表食品本身的菌群 |
| `not_food`* | 推测为加工环境（地面、下水道、刀具、动物皮、粪便等）或饲料，不是食品 |
| `long_read` | Nanopore / PacBio 长读长数据 |
| `filetype_bam` | 文件是 BAM 格式 |
| `source_*` | 文库来源登记的不是 METAGENOMIC（多为登记错误） |
| `gsa_strategy_other` | GSA 中测序策略登记为 Other，但从数据量判断是 shotgun |
| `no_md5` | 没有校验码，下载后只核对文件大小 |
| `not_found_in_archive` | cFMD 中有记录，但在数据库中没有找到 |

推荐数据（`recommended` = yes）= core 档，并且没有带 * 的标记。

## 七、更新清单

数据库会不断新增数据。重新生成清单：

```bash
python3 scripts/build_catalog.py            # 第一次约半小时；之后使用 raw/ 中的缓存，约 1 分钟
python3 scripts/build_catalog.py --refresh  # 忽略缓存，重新查询所有数据库，约半小时
```

结果会覆盖 `catalog/` 中的文件。如果要调整查询的名称或关键词，修改 `scripts/build_catalog.py` 开头的 `FOOD_TAXA` 和 `KEYWORDS`。

## 八、只需要物种或功能丰度的话

如果分析只需要每个样本的物种组成或功能组成，不一定要下载原始数据。cFMD 已经为其中 4,125 个样本算好了 MetaPhlAn 4 物种丰度和功能谱，可以直接从 https://github.com/SegataLab/cFMD 获取。

## 九、注意事项

- cFMD 以外的样本，食品类别是根据描述自动推测的，可能有误。GSA 的数据没有样本描述，大多没有类别。
- 同一份数据如果同时提交到 GSA 和国际库，清单里可能出现两次。
- GSA 没有官方接口，清单脚本用的是它网页背后的接口，网站改版后可能需要调整。
- 发表时请引用原始数据所属的项目。使用 cFMD 请引用：Carlino N, et al. Unexplored microbial diversity from 2,500 food metagenomes and links with the human microbiome. *Cell* 2024;187(20):5775–5795.
- 少数样本描述里提交者留下的邮箱和电话，已替换为 `[email removed]` / `[phone removed]`。

## 十、许可

- 脚本采用 MIT 许可（见 `LICENSE`）。
- 清单中来自 cFMD 的内容（食品分类等）采用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 许可，使用时请引用上面的 cFMD 论文。
- 其余信息来自 ENA / NCBI / DDBJ 和 GSA 的公开记录。
