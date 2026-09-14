# DOORS 中文维基 · 模板同步与翻译规范

你负责把英文 DOORS 维基（doorsgame.wiki）的模板同步到中文维基（zh.doorsgame.wiki）的版本，并把模板里**用户看得见**的文字译成中文。

## 工作方式

每个模板有一组固定路径（批次 JSON 里逐条给出）：

- 英文最新源码：`pages_src/templates/<名称>.en.mw`（`/` 在文件名里写作 `__`）
- 中文现状：`pages_zh/templates/<名称>.zh.mw`
- 你的输出：`pages_zh/templates/new/<名称>.zh.new.mw`

对每个模板：读英文源（这是结构基准）+ 读中文现状（里面可能已有经过审校的中文，能复用就复用），写出**完整的新中文版**到输出路径。用 write 工具整文件写入，UTF-8。

**不要上传到 wiki**，不要调用任何写接口。

## 结构规则（必须与英文源一致）

1. 模板名、参数名、`{{{参数|默认值}}}`、解析器函数（`#if`/`#switch`/`#ifeq`/`#vardefine`/`#invoke`…）、HTML 标签、`<includeonly>`/`<noinclude>`/`<onlyinclude>`、`<infobox>` 的 `source=` 属性、CSS 类名、`style="…"`、`<templatestyles>`、`[[Category:…]]`、`[[File:…]]` 文件名、URL、`<ref>`、注释 `<!-- -->` 全部原样保留。
2. 英文源如果比中文现状多了/改了内容（`needs_sync: true`），一律以英文源为准补上或改掉，同时保留中文现状里已有的中文译文（英文原文没变的部分直接沿用旧中文）。
3. 只翻译「渲染出来给人看的文字」：信息框的 `<label>`/`<header>`/`labelN =`、提示模板的正文、表格表头、按钮/工具提示文字、`alt=` 描述、`<default>` 里的默认显示文字、图注等。
4. 参数名、模板名、模块名、分类名、链接目标（`[[X|显示文字]]` 的 X）、文件名一律不翻译。

## 术语表（必须统一）

信息框标签：Rooms→房间数；Released→发布日期；Removed→移除日期；Developers→开发者；Previous→上一个；Next→下一个；Main Info→主要信息；Attack→攻击；Damage→伤害；Floors→楼层；Rooms Present→出现房间；Spawn Rate→刷新率；Date Added→加入日期；Creator(s)→创作者；Sound Files→音效文件；Amount→数量；Durability→耐久度；Price→价格；Description→描述；Requirement→要求；Information→信息；Additional Information→补充信息；Details→详情；Notes→注释；Hiding Spots→藏身点；Header→标题；Section→章节；Type→类型；Gender→性别；Species→物种；Birthday→生日；Favorite/Favorites→最爱；Occupation→职业；Alias/Aliases→别名；Health→生命值；Speed→速度；Intelligence→智力；Mechanical→机械；Hazardous→危险；Unknown→未知；Medium→中等；High→高；Danger→危险；Progress→进度；Rewards→奖励；Challenges→挑战；Modifiers→修饰符；Achievements→成就；Badges→徽章；Trivia→冷知识；Gallery→图库；Appearance→外观；Behavior→行为；Usage→用法；Features→功能；Cosmetics→外观。

维护/通知模板：Deletion→删除；Move→移动；Merge→合并；Protect→保护；Orphan→孤立页面；Inactivity→长期不活跃；Stub→不完善的作品；Outdated→内容过时；Upcoming→即将推出；Conjecture→推测内容；Clean→需要清理；Spoiler→剧透；Trigger warning→敏感内容警告；Disambiguation→消歧义；Citation needed→需要来源；Theory→理论；Returning→回归内容；Discontinued→已停止；Admin Exclusive→管理员专属；Exploiting→利用漏洞；Userpage→用户页；Contributor→贡献者；Staff→工作人员；Credits→制作人员；Fair use→合理使用；Copyright→版权；License→许可协议；Permission→授权；Public domain→公有领域；Self-made→自制作品；From Wikimedia→来自维基共享资源。

通用词：Expand→展开；Collapse→收起；Show→显示；Hide→隐藏；Click→点击；Edit→编辑；History→历史；Talk→讨论；Help→帮助；Project page→项目页面；Template→模板；Category→分类；File→文件；Module→模块；User page→用户页；Article→条目；This template→本模板；This article→本条；This page→本页面；Please→请。

保留英文的专有名词：实体名（Rush、Ambush、Seek、Figure、Screech、Dupe、Eyes、Halt、Hide、Void、Glitch、Jack、Timothy、Dread、Sally、Giggle、Gloombat、Louie、Grumble、Blitz、Lookman、Haste、Honcho、Alma、Cobble、Portrait、Ransom、Drone、Bash、Stem、Fih、Creak、Teller、Hijack、Noise、A-60、A-90、A-120…）、楼层名、物品名（Knobs、Gold、Stardust、Boosts、Revives、Rift、Lotus、Skeleton Key、Lockpick、Shakelight、Flashlight、Lighter、Candle、Smoothie、Green Herb、Shears、Straplight、Moonlight Candle、Honey Pot、Pizza、Bread、Cheese、Nanner、Boxing Gloves…）、成就/徽章/modifier 名、Vision 名、`DOORS`、`LSPLASH`、`Roblox`、`Fandom`、用户名。

## 文风

中文要像中文维基编辑写的：不要「此外」「不仅……而且」「标志着」「彰显」「值得注意的是」这类填充词；少用破折号；英文长句拆成中文短句；数字与中文之间加空格（如「250 个房间」），英文专有名词与中文之间也加空格。

## 自检（写文件前逐项过）

1. 与英文源对照：`{{`/`}}`、`[[`/`]]`、`<includeonly>`/`</includeonly>` 数量一致；`[[File:…]]` 文件名逐一相同；`[[Category:…]]` 完全相同；参数名集合相同。
2. 输出里没有残留的英文整句（专有名词、参数名、CSS、文件名、URL、链接目标除外）。
3. 没有草稿痕迹（TODO/待补/wait 等）。
4. 如果模板本身是 `#REDIRECT`（重定向），直接照抄英文源，不要翻译。

## 交付报告

用中文简短报告：处理的每个模板一行（模板名 → 输出路径、字符数、是否同步了代码、翻译了哪些可见文字），最后列出拿不准的术语。不要粘贴全文。
